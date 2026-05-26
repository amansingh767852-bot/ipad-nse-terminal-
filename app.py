import streamlit as st
import pandas as pd
from datetime import datetime
import time

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

# -- Fetching NSE Data --
@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    """
    Fetches option chain and futures data from NSE using the server-optimized library.
    Returns option_chain_df, futures_df, and a metrics dictionary.
    """
    try:
        # Use the NSE library's server-optimized version
        from nse import NSE
        from pathlib import Path
        
        # Create a folder for cache files (works on any server or local machine)
        download_folder = Path("./nse_cache")
        download_folder.mkdir(exist_ok=True)
        
        # The server=True flag is crucial for cloud environments like Streamlit Cloud
        with NSE(download_folder=download_folder, server=True) as nse:
            # Fetch option chain data
            oc_data = nse.option_chain(symbol=symbol)
            if oc_data is None:
                st.error(f"Could not fetch option chain data for {symbol}. NSE might be rate-limiting. Please wait a moment and try again.")
                return None, None, None

            # Fetch futures data
            fut_data = nse.live_equity_derivatives(symbol=symbol)
            if fut_data is None:
                st.error(f"Could not fetch futures data for {symbol}. NSE might be rate-limiting. Please wait a moment and try again.")
                return None, None, None

            # The library returns data as DataFrames, perfect for our needs
            return oc_data, fut_data

    except ImportError:
        st.error("The 'nse' library is not installed. Please run: pip install nse[server]")
        return None, None, None
    except Exception as e:
        st.error(f"An unexpected error occurred while fetching data: {str(e)}. This might be a temporary network issue. Please try again in a few seconds.")
        return None, None, None


def process_terminal(oc_data, fut_data):
    """
    Processes the raw data from fetch_nse_data, extracting:
    - Option chain DataFrame with OI for CE/PE
    - Futures DataFrame for the next 3 expiries
    - Metrics: PCR, Support, Resistance
    """
    if oc_data is None or fut_data is None:
        return None, None, None

    try:
        # --- Process Options Data ---
        # The option_chain method returns a dictionary with 'records', 'strikePrices', etc.
        # We need to transform it into a clean DataFrame similar to the original code.
        records = oc_data.get('records', {})
        if not records:
            st.warning("Option chain data was received but is empty. NSE may be experiencing issues.")
            return None, None, None

        raw_oc = records.get('data', [])
        expiry = records.get('expiryDates', [None])[0]
        if expiry is None or not raw_oc:
            st.warning("No expiry dates or option data found. Please check if the market is open.")
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
        # The live_equity_derivatives method returns a list of future contracts
        fut_list = []
        seen_exp = set()
        for item in fut_data:
            meta = item.get('metadata', {})
            if meta.get('instrumentType') in ['Index Futures', 'Stock Futures']:
                exp = meta.get('expiryDate')
                # Collect up to 3 unique expiry dates
                if exp not in seen_exp and len(seen_exp) < 3:
                    seen_exp.add(exp)
                    fut_list.append({
                        'Expiry': exp,
                        'LTP': item.get('lastPrice', 0),
                        'Chg%': item.get('pChange', 0),
                        'OI': item.get('openInterest', 0),
                        'Chg_OI%': item.get('pchangeinOpenInterest', 0)
                    })
        df_fut = pd.DataFrame(fut_list)

        # --- Calculate Metrics ---
        if not df_opt.empty:
            total_ce = df_opt['CE_OI'].sum()
            total_pe = df_opt['PE_OI'].sum()
            pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
            resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike']
            support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike']
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
        st.error(f"An error occurred while processing data: {str(e)}. The data format from NSE might have changed. Please contact support.")
        return None, None, None


# --- UI Display ---
st.title("Live NSE Terminal: Option Chain & Futures")

# Sidebar for user inputs
symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()  # Force a full refresh of the app

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
    st.error("Unable to fetch data from NSE. This could be due to:")
    st.error("1. The NSE servers are busy. Please wait a few seconds and click 'Refresh Data'.")
    st.error("2. You're behind a strict firewall. Try running the app on a different network.")
    st.error("3. The market might be closed. NSE data is only available during market hours.")
