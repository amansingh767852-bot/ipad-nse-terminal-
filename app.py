import streamlit as st
import pandas as pd
import nselib
from datetime import datetime

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

# --- Data Fetching ---
@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    """Fetches live option chain data using nselib."""
    try:
        # This is the correct function from the nselib library
        option_chain_data = nselib.derivatives.nse_live_option_chain(symbol=symbol)
        return option_chain_data
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return None

def generate_demo_data(symbol):
    """Generates demo data when live fetch fails."""
    import random
    random.seed(42)
    
    # Create demo option chain
    strikes = [22500, 22600, 22700, 22800, 22900, 23000, 23100, 23200, 23300, 23400, 23500]
    demo_data = []
    for strike in strikes:
        demo_data.append({
            'CE OI': random.randint(100000, 1000000),
            'CE Change OI': random.randint(-50000, 50000),
            'CE LTP': round(random.uniform(10, 200), 2),
            'Strike': strike,
            'PE LTP': round(random.uniform(10, 200), 2),
            'PE Change OI': random.randint(-50000, 50000),
            'PE OI': random.randint(100000, 1000000)
        })
    
    df_opt = pd.DataFrame(demo_data)
    
    # Futures placeholder
    df_fut = pd.DataFrame([
        {'Expiry': '28-May-2026', 'LTP': 0, 'Change %': 0, 'OI': 0, 'OI Change %': 0}
    ])
    
    total_ce = df_opt['CE OI'].sum()
    total_pe = df_opt['PE OI'].sum()
    pcr = round(total_pe / total_ce, 2)
    resistance = df_opt.loc[df_opt['CE OI'].idxmax()]['Strike']
    support = df_opt.loc[df_opt['PE OI'].idxmax()]['Strike']
    
    metrics = {
        'PCR': pcr,
        'Support': support,
        'Resistance': resistance,
        'Expiry': 'Demo Data',
        'Time': datetime.now().strftime("%H:%M:%S"),
        'Mode': '⚠️ DEMO MODE (Live data unavailable)'
    }
    return df_opt, df_fut, metrics

def process_live_data(data, symbol):
    """Process the raw data from nselib into our required format."""
    if data is None or data.empty:
        return None, None, None
    
    try:
        # The nselib data comes as a DataFrame; we just need to ensure column names match
        df_opt = data.copy()
        
        # Rename columns to match the app's expected format
        column_mapping = {
            'ce_openInterest': 'CE OI',
            'ce_changeinOpenInterest': 'CE Change OI', 
            'ce_lastPrice': 'CE LTP',
            'strikePrice': 'Strike',
            'pe_lastPrice': 'PE LTP',
            'pe_changeinOpenInterest': 'PE Change OI',
            'pe_openInterest': 'PE OI'
        }
        df_opt = df_opt.rename(columns=column_mapping)
        
        # Create futures placeholder
        df_fut = pd.DataFrame([
            {'Expiry': 'N/A', 'LTP': 0, 'Change %': 0, 'OI': 0, 'OI Change %': 0}
        ])
        
        # Calculate metrics
        total_ce = df_opt['CE OI'].sum() if 'CE OI' in df_opt.columns else 0
        total_pe = df_opt['PE OI'].sum() if 'PE OI' in df_opt.columns else 0
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        
        resistance = df_opt.loc[df_opt['CE OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        support = df_opt.loc[df_opt['PE OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        
        metrics = {
            'PCR': pcr,
            'Support': support,
            'Resistance': resistance,
            'Expiry': 'Current Expiry',
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Mode': '✅ LIVE DATA'
        }
        return df_opt, df_fut, metrics
    
    except Exception as e:
        st.error(f"Error processing data: {e}")
        return None, None, None

# --- UI ---
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Fetch and display data
data = fetch_nse_data(symbol)
if data is not None and not data.empty:
    df_opt, df_fut, metrics = process_live_data(data, symbol)
else:
    df_opt, df_fut, metrics = generate_demo_data(symbol)

if metrics:
    st.info(f"{metrics['Mode']} | Last Sync: {metrics['Time']} | Expiry: {metrics['Expiry']}")
    
    # Display metrics in columns
    col1, col2, col3 = st.columns(3)
    col1.metric("Put-Call Ratio (PCR)", metrics['PCR'])
    col2.metric("Support Wall (Max PE OI)", f"₹{metrics['Support']}")
    col3.metric("Resistance Wall (Max CE OI)", f"₹{metrics['Resistance']}")
    
    st.markdown("---")
    
    # Futures table
    st.subheader("Futures Data")
    st.dataframe(df_fut, use_container_width=True)
    
    # Option Chain table
    st.subheader("Option Chain")
    if not df_opt.empty:
        st.dataframe(df_opt, use_container_width=True, height=600)
    else:
        st.warning("No option chain data available.")
else:
    st.error("Unable to load any data. Please check your connection.")
