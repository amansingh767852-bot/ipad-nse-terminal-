import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")


# -- Fetching NSE Data --
@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    try:
        # Import the server-optimized version of the library
        import nsepythonserver as nse
        from pathlib import Path

        # A small folder is needed for caching purposes by the library
        download_folder = Path("./nse_cache")
        download_folder.mkdir(exist_ok=True)

        # Setting `server=True` is the key for cloud environments
        nse_api = nse.NSE(download_folder=download_folder, server=True)

        # Fetch the option chain data
        # The library expects the symbol in lowercase
        oc_data = nse_api.optionchain(symbol=symbol.lower())

        if not oc_data or not oc_data.get("records", {}).get("data"):
            st.warning(
                f"No option chain data found for {symbol}. This can happen outside market hours (9:15 AM - 3:30 PM IST) or if the symbol is incorrect."
            )
            return None, None

        # Futures data is not directly available from this function,
        # so we'll create a placeholder. You can enhance this later.
        fut_data = None

        return oc_data, fut_data

    except ImportError:
        st.error(
            "The server-optimized library is not installed. Please run: pip install nsepythonserver"
        )
        return None, None
    except Exception as e:
        st.error(f"An error occurred while fetching data: {str(e)}")
        return None, None


def process_terminal(oc_data, fut_data):
    if oc_data is None:
        return None, None, None

    try:
        # Extract records and expiry date from the option chain data
        records = oc_data.get("records", {})
        if not records:
            st.warning("Option chain data was received but is empty.")
            return None, None, None

        raw_oc = records.get("data", [])
        expiry = records.get("expiryDates", [None])[0]
        if expiry is None or not raw_oc:
            st.warning("No expiry dates or option data found.")
            return None, None, None

        # --- Build the Option Chain DataFrame ---
        opt_list = []
        for item in raw_oc:
            if item.get("expiryDate") != expiry:
                continue
            strike = item.get("strikePrice")
            ce = item.get("CE", {})
            pe = item.get("PE", {})
            opt_list.append(
                {
                    "CE_OI": ce.get("openInterest", 0),
                    "CE_Chg_OI": ce.get("changeinOpenInterest", 0),
                    "CE_LTP": ce.get("lastPrice", 0),
                    "Strike": strike,
                    "PE_LTP": pe.get("lastPrice", 0),
                    "PE_Chg_OI": pe.get("changeinOpenInterest", 0),
                    "PE_OI": pe.get("openInterest", 0),
                }
            )

        if not opt_list:
            st.warning("No option chain data available for the selected expiry.")
            return None, None, None

        df_opt = pd.DataFrame(opt_list)

        # --- Create a Placeholder for Futures Data ---
        fut_list = []
        # You can replace this with a dedicated API call later
        for i in range(3):
            fut_list.append(
                {
                    "Expiry": f"{expiry}",  # Placeholder data
                    "LTP": 0,
                    "Chg%": 0,
                    "OI": 0,
                    "Chg_OI%": 0,
                }
            )
        df_fut = pd.DataFrame(fut_list)

        # --- Calculate Metrics (PCR, Support, Resistance) ---
        total_ce = df_opt["CE_OI"].sum()
        total_pe = df_opt["PE_OI"].sum()
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0

        resistance = (
            df_opt.loc[df_opt["CE_OI"].idxmax()]["Strike"] if not df_opt.empty else 0
        )
        support = (
            df_opt.loc[df_opt["PE_OI"].idxmax()]["Strike"] if not df_opt.empty else 0
        )

        metrics = {
            "PCR": pcr,
            "Support": support,
            "Resistance": resistance,
            "Expiry": expiry,
            "Time": datetime.now().strftime("%H:%M:%S"),
        }

        return df_opt, df_fut, metrics

    except Exception as e:
        st.error(f"An error occurred while processing data: {str(e)}")
        return None, None, None


# --- UI Display ---
st.title("Live NSE Terminal: Option Chain & Futures")

# Sidebar for user inputs
symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    # Clear the cached data to force a fresh fetch from NSE
    st.cache_data.clear()
    st.rerun()

# Fetch and process data
oc_data, fut_data = fetch_nse_data(symbol)
df_opt, df_fut, metrics = process_terminal(oc_data, fut_data)

if metrics:
    st.write(f"**Last Sync:** {metrics['Time']} | **Near Expiry:** {metrics['Expiry']}")

    # Display Key Metrics in 3 Columns
    c1, c2, c3 = st.columns(3)
    c1.metric("Put-Call Ratio (PCR)", metrics["PCR"])
    c2.metric("Support Wall (Max PE OI)", f"₹{metrics['Support']}")
    c3.metric("Resistance Wall (Max CE OI)", f"₹{metrics['Resistance']}")

    st.markdown("---")

    # Display Futures Data (Placeholder)
    st.subheader("Combined Futures Flow (Next 3 Expiries)")
    st.dataframe(df_fut, use_container_width=True)

    # Display Option Chain Data
    st.subheader("Live Option Chain")
    if not df_opt.empty:
        # Apply conditional formatting: CE_OI in red gradient, PE_OI in green gradient
        styled_opt = df_opt.style.background_gradient(cmap="Reds", subset=["CE_OI"])
        styled_opt = styled_opt.background_gradient(cmap="Greens", subset=["PE_OI"])
        st.dataframe(styled_opt, use_container_width=True, height=600)
    else:
        st.warning("No option chain data available at the moment.")
else:
    st.error(
        "Unable to fetch data. This could be because the market is closed or NSE is currently rate-limiting requests."
    )
