import streamlit as st
import pandas as pd
from datetime import datetime
import time

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    try:
        from nselib import derivatives
        
        # Fetch the live option chain using nselib
        option_chain_df = derivatives.nse_live_option_chain(symbol=symbol)
        
        if option_chain_df is None or option_chain_df.empty:
            st.warning(f"No option chain data found for {symbol}. The market might be closed or the symbol is invalid.")
            return None, None
        
        return option_chain_df, None
    
    except ImportError:
        st.error("The required library is not installed. Please run: pip install nselib")
        return None, None
    except Exception as e:
        st.error(f"Data fetch error: {str(e)}")
        return None, None

def generate_demo_data(symbol):
    """Generates realistic mock data when live data is unavailable."""
    base_strikes = [i for i in range(22000, 26000, 100)] if symbol == "NIFTY" else [i for i in range(44000, 56000, 200)]
    expiry = datetime.now().strftime("%d-%b-%Y")
    
    opt_list = []
    for strike in base_strikes:
        ce_oi = abs(hash(f"{symbol}{strike}")) % 500000 + 50000
        pe_oi = abs(hash(f"{symbol}{strike}_pe")) % 500000 + 50000
        opt_list.append({
            'CE_OI': ce_oi,
            'CE_Chg_OI': (hash(f"{symbol}{strike}_chg") % 10000) - 5000,
            'CE_LTP': round(abs(hash(f"{symbol}{strike}_ltp")) % 500, 1),
            'Strike': strike,
            'PE_LTP': round(abs(hash(f"{symbol}{strike}_pe_ltp")) % 500, 1),
            'PE_Chg_OI': (hash(f"{symbol}{strike}_pe_chg") % 10000) - 5000,
            'PE_OI': pe_oi
        })
    df_opt = pd.DataFrame(opt_list)
    
    fut_list = []
    for i in range(3):
        fut_list.append({
            'Expiry': f"{(datetime.now().replace(day=28) if i == 0 else datetime.now().replace(month=datetime.now().month + i, day=28)).strftime('%d-%b-%Y')}",
            'LTP': round(22000 + (hash(f"{symbol}_fut_{i}") % 1000), 2),
            'Chg%': round(((hash(f"{symbol}_fut_{i}_chg") % 200) - 100) / 100, 2),
            'OI': abs(hash(f"{symbol}_fut_{i}_oi")) % 1000000 + 100000,
            'Chg_OI%': round(((hash(f"{symbol}_fut_{i}_oi_chg") % 200) - 100) / 100, 2)
        })
    df_fut = pd.DataFrame(fut_list)
    
    total_ce = df_opt['CE_OI'].sum()
    total_pe = df_opt['PE_OI'].sum()
    pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 1.2
    resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike']
    support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike']
    
    metrics = {
        'PCR': pcr,
        'Support': support,
        'Resistance': resistance,
        'Expiry': expiry,
        'Time': datetime.now().strftime("%H:%M:%S"),
        'Mode': "🔹 DEMO MODE (NSE data unavailable)"
    }
    return df_opt, df_fut, metrics

def process_terminal(oc_data, fut_data):
    if oc_data is None or oc_data.empty:
        return generate_demo_data("NIFTY")  # Fallback to demo data
    
    try:
        # The data from nselib is already a DataFrame in the expected format
        df_opt = oc_data.copy()
        
        # Extract nearest expiry date from the data if available
        expiry = df_opt['expiryDate'].iloc[0] if 'expiryDate' in df_opt.columns else datetime.now().strftime("%d-%b-%Y")
        
        # Ensure the column names match what the UI expects
        column_mapping = {
            'strikePrice': 'Strike',
            'ce_openInterest': 'CE_OI',
            'ce_changeinOpenInterest': 'CE_Chg_OI',
            'ce_lastPrice': 'CE_LTP',
            'pe_lastPrice': 'PE_LTP',
            'pe_changeinOpenInterest': 'PE_Chg_OI',
            'pe_openInterest': 'PE_OI'
        }
        df_opt = df_opt.rename(columns={k: v for k, v in column_mapping.items() if k in df_opt.columns})
        
        # Create placeholder futures data (enhanceable later)
        df_fut = pd.DataFrame([
            {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg_OI%': 0},
            {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg_OI%': 0},
            {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg_OI%': 0}
        ])
        
        total_ce = df_opt['CE_OI'].sum() if 'CE_OI' in df_opt.columns else 0
        total_pe = df_opt['PE_OI'].sum() if 'PE_OI' in df_opt.columns else 0
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        
        support = resistance = 0
        if 'CE_OI' in df_opt.columns and 'Strike' in df_opt.columns and not df_opt.empty:
            resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike']
            support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike']
        
        metrics = {
            'PCR': pcr,
            'Support': support,
            'Resistance': resistance,
            'Expiry': expiry,
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Mode': "✅ LIVE DATA (real NSE)"
        }
        return df_opt, df_fut, metrics
    
    except Exception as e:
        st.error(f"Processing error: {str(e)}. Falling back to demo mode.")
        return generate_demo_data("NIFTY")

# --- UI Display ---
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
force_demo = st.sidebar.checkbox("Use Demo Mode (mock data)", value=False)

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

if force_demo:
    df_opt, df_fut, metrics = generate_demo_data(symbol)
else:
    oc_data, fut_data = fetch_nse_data(symbol)
    df_opt, df_fut, metrics = process_terminal(oc_data, fut_data)

if metrics:
    st.info(f"{metrics['Mode']} | Last Sync: {metrics['Time']} | Near Expiry: {metrics['Expiry']}")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Put-Call Ratio (PCR)", metrics['PCR'])
    c2.metric("Support Wall (Max PE OI)", f"₹{metrics['Support']}")
    c3.metric("Resistance Wall (Max CE OI)", f"₹{metrics['Resistance']}")
    
    st.markdown("---")
    st.subheader("Combined Futures Flow (Next 3 Expiries)")
    st.dataframe(df_fut, use_container_width=True)
    
    st.subheader("Live Option Chain")
    if not df_opt.empty:
        # Safely apply styling only to existing columns
        style_kwargs = {}
        if 'CE_OI' in df_opt.columns:
            style_kwargs['subset'] = ['CE_OI']
            styled_opt = df_opt.style.background_gradient(cmap='Reds', subset=['CE_OI'])
        else:
            styled_opt = df_opt.style
        
        if 'PE_OI' in df_opt.columns:
            styled_opt = styled_opt.background_gradient(cmap='Greens', subset=['PE_OI'])
        
        st.dataframe(styled_opt, use_container_width=True, height=600)
    else:
        st.warning("No option chain data available.")
else:
    st.error("Unable to fetch data. Please check your network connection and try again.")
