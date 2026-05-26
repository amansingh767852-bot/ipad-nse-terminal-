import streamlit as st
import pandas as pd
from datetime import datetime
import time

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

# -- Fetching NSE Data --
@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    try:
        # Use nsepython library, which is reliable for server environments
        import nsepython as nse
        from pathlib import Path

        # Convert symbol to lowercase as the library expects
        symbol_lower = symbol.lower()
        
        # Fetch option chain data directly with the correct method
        oc_data = nse.option_chain(symbol_lower)
        if oc_data is None:
            st.error(f"Could not fetch option chain data for {symbol}. Please try again.")
            return None, None

        # For futures data, we'll use the existing option chain as it contains the needed info
        # In a future update, you could add dedicated futures data fetching
        fut_data = oc_data

        return oc_data, fut_data

    except ImportError:
        st.error("The 'nsepython' library is not installed. Please run: pip install nsepython")
        return None, None
    except Exception as e:
        st.error(f"An unexpected error occurred while fetching data: {str(e)}")
        return None, None

def process_terminal(oc_data, fut_data):
    if oc_data is None or fut_data is None:
        return None, None, None

    try:
        # Extract records from the option chain data
        records = oc_data.get('records', {})
        if not records:
            st.warning("Option chain data was received but is empty.")
            return None, None, None

        raw_oc = records.get('data', [])
        expiry = records.get('expiryDates', [None])[0]
        if expiry is None or not raw_oc:
            st.warning("No expiry dates or option data found.")
            return None, None, None

        opt_list = []
        for item in raw_oc:
            if item.get('expiryDate') != expiry:
                continue
            strike = item.get('strikePrice')
            ce = item.get('CE', {})
            pe = item.get('PE', {})
            opt_list.append({
                'CE_OI': ce.get('openInterest', 0),
                'CE_Chg_OI': ce.get('changeinOpenInterest', 0),
                'CE_LTP': ce.get('lastPrice', 0),
                'Strike': strike,
                'PE_LTP': pe.get('lastPrice', 0),
                'PE_Chg_OI': pe.get('changeinOpenInterest', 0),
                'PE_OI': pe.get('openInterest', 0)
            })
        df_opt = pd.DataFrame(opt_list)

        # --- Process Futures Data ---
        # For now, we'll create a placeholder DataFrame as the library doesn't provide dedicated futures data
        # In a future update, you could add a separate API call for futures data
        fut_list = []
        # This is a placeholder; you can add more complex logic here
        for i in range(3):
            fut_list.append({
                'Expiry': f"{expiry}",  # Placeholder, replace with actual expiry dates
                'LTP': 0,  # Placeholder, replace with actual LTP
                'Chg%': 0,  # Placeholder, replace with actual Chg%
                'OI': 0,  # Placeholder, replace with actual OI
                'Chg_OI%': 0  # Placeholder, replace with actual Chg_OI%
            })
        df_fut = pd.DataFrame(fut_list)

        # --- Calculate Metrics ---
        if not df_opt.empty:
            total_ce = df_opt['CE_OI'].sum()
            total_pe = df_opt['PE_OI'].sum()
            pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
            resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike'] if not df_opt.empty else 0
            support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        else:
            pcr = 0
            resistance = 0
            support = 0

        metrics = {
            'PCR': pcr,
            'Support': support,
            'Resistance': resistance,
            'Expiry': expiry,
            'Time': datetime.now().strftime("%H:%M:%S")
        }

        return df_opt, df_fut, metrics

    except Exception as e:
        st.error(f"An error occurred while processing data: {str(e)}.")
        return None, None, None


# --- UI Display ---
st.title("Live NSE Terminal: Option Chain & Futures")

# Sidebar for user inputs
symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Fetch and process data
oc_data, fut_data = fetch_nse_data(symbol)
df_opt, df_fut, metrics = process_terminal(oc_data, fut_data)

if metrics:
    st.write(f"**Last Sync:** {metrics['Time']} | **Near Expiry:** {metrics['Expiry']}")

    # Display Key Metrics in 3 Columns
    c1, c2, c3 = st.columns(3)
    c1.metric("Put-Call Ratio (PCR)", metrics['PCR'])
    c2.metric("Support Wall (Max PE OI)", f"₹{metrics['Support']}")
    c3.metric("Resistance Wall (Max CE OI)", f"₹{metrics['Resistance']}")

    st.markdown("---")

    # Display Futures Data
    st.subheader("Combined Futures Flow (Next 3 Expiries)")
    if not df_fut.empty:
        st.dataframe(df_fut, use_container_width=True)
    else:
        st.warning("No futures data available at the moment.")

    # Display Option Chain Data
    st.subheader("Live Option Chain")
    if not df_opt.empty:
        # Apply conditional formatting: CE_OI in red gradient, PE_OI in green gradient
        styled_opt = df_opt.style.background_gradient(cmap='Reds', subset=['CE_OI'])
        styled_opt = styled_opt.background_gradient(cmap='Greens', subset=['PE_OI'])
        st.dataframe(styled_opt, use_container_width=True, height=600)
    else:
        st.warning("No option chain data available at the moment.")
else:
    st.error("Unable to fetch data from NSE. Please ensure you have installed 'nsepython' and try again.")
