import streamlit as st
import pandas as pd
import requests
import time
import random
from datetime import datetime

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

# ------------------- Helper Functions -------------------
def generate_demo_data(symbol):
    """Generate realistic mock data when live data is unavailable."""
    random.seed(hash(symbol) % 2**32)
    
    # Define strikes based on symbol
    if symbol == "NIFTY":
        base = 22000
        strikes = list(range(base, base + 4000, 100))
    elif symbol == "BANKNIFTY":
        base = 44000
        strikes = list(range(base, base + 8000, 200))
    else:  # FINNIFTY
        base = 20000
        strikes = list(range(base, base + 3000, 100))
    
    expiry = datetime.now().strftime("%d-%b-%Y")
    opt_list = []
    for strike in strikes:
        ce_oi = random.randint(50000, 800000)
        pe_oi = random.randint(50000, 800000)
        opt_list.append({
            'CE_OI': ce_oi,
            'CE_Chg_OI': random.randint(-20000, 20000),
            'CE_LTP': round(random.uniform(5, 300), 1),
            'Strike': strike,
            'PE_LTP': round(random.uniform(5, 300), 1),
            'PE_Chg_OI': random.randint(-20000, 20000),
            'PE_OI': pe_oi
        })
    df_opt = pd.DataFrame(opt_list)
    
    # Futures data - 3 expiries
    fut_list = []
    for i in range(3):
        expiry_date = datetime.now().replace(day=28)
        if i == 1:
            expiry_date = expiry_date.replace(month=expiry_date.month + 1)
        elif i == 2:
            expiry_date = expiry_date.replace(month=expiry_date.month + 2)
        fut_list.append({
            'Expiry': expiry_date.strftime('%d-%b-%Y'),
            'LTP': round(random.uniform(22000, 24000), 2),
            'Chg%': round(random.uniform(-2, 2), 2),
            'OI': random.randint(200000, 2000000),
            'Chg_OI%': round(random.uniform(-5, 5), 2)
        })
    df_fut = pd.DataFrame(fut_list)
    
    total_ce = df_opt['CE_OI'].sum()
    total_pe = df_opt['PE_OI'].sum()
    pcr = round(total_pe / total_ce, 2) if total_ce else 1.2
    resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike']
    support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike']
    
    metrics = {
        'PCR': pcr,
        'Support': support,
        'Resistance': resistance,
        'Expiry': expiry,
        'Time': datetime.now().strftime("%H:%M:%S"),
        'Mode': "🔹 DEMO MODE (market closed or offline)"
    }
    return df_opt, df_fut, metrics

def fetch_live_data(symbol):
    """Try to fetch real data from NSE (works during market hours)."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }
    session.headers.update(headers)
    
    base_url = "https://www.nseindia.com"
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    
    try:
        # First visit homepage to get cookies
        session.get(base_url, timeout=15)
        time.sleep(2)
        # Then fetch data
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data
    except Exception as e:
        st.warning(f"Live data not available: {str(e)[:100]}")
        return None

def process_live_data(data, symbol):
    """Convert live JSON into DataFrames."""
    if not data or 'records' not in data:
        return None, None, None
    
    records = data['records']
    raw_oc = records.get('data', [])
    if not raw_oc:
        return None, None, None
    
    expiry = records['expiryDates'][0]
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
    
    # Simple futures placeholder (you can enhance later)
    df_fut = pd.DataFrame([
        {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg_OI%': 0},
        {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg_OI%': 0},
        {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg_OI%': 0}
    ])
    
    total_ce = df_opt['CE_OI'].sum()
    total_pe = df_opt['PE_OI'].sum()
    pcr = round(total_pe / total_ce, 2) if total_ce else 0
    resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike'] if not df_opt.empty else 0
    support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike'] if not df_opt.empty else 0
    
    metrics = {
        'PCR': pcr,
        'Support': support,
        'Resistance': resistance,
        'Expiry': expiry,
        'Time': datetime.now().strftime("%H:%M:%S"),
        'Mode': "✅ LIVE DATA (real NSE)"
    }
    return df_opt, df_fut, metrics

# ------------------- UI -------------------
st.title("Live NSE Terminal: Option Chain & Futures")

# Sidebar
symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
force_demo = st.sidebar.checkbox("Force Demo Mode (mock data)", value=False)

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Fetch data
if force_demo:
    df_opt, df_fut, metrics = generate_demo_data(symbol)
else:
    live_json = fetch_live_data(symbol)
    if live_json:
        df_opt, df_fut, metrics = process_live_data(live_json, symbol)
        if df_opt is None or df_opt.empty:
            st.warning("Live data empty – switching to demo mode")
            df_opt, df_fut, metrics = generate_demo_data(symbol)
    else:
        df_opt, df_fut, metrics = generate_demo_data(symbol)

# Display everything
if metrics is not None:
    st.info(f"{metrics['Mode']} | Last Sync: {metrics['Time']} | Expiry: {metrics['Expiry']}")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Put-Call Ratio (PCR)", metrics['PCR'])
    col2.metric("Support Wall (Max PE OI)", f"₹{metrics['Support']}")
    col3.metric("Resistance Wall (Max CE OI)", f"₹{metrics['Resistance']}")
    
    st.markdown("---")
    st.subheader("Combined Futures Flow (Next 3 Expiries)")
    st.dataframe(df_fut, use_container_width=True)
    
    st.subheader("Live Option Chain")
    if not df_opt.empty:
        # Safely apply styling only if columns exist
        styled = df_opt.copy()
        if 'CE_OI' in styled.columns:
            styled = styled.style.background_gradient(cmap='Reds', subset=['CE_OI'])
        if 'PE_OI' in styled.columns:
            # Handle case where styled is already a Styler
            if hasattr(styled, 'background_gradient'):
                styled = styled.background_gradient(cmap='Greens', subset=['PE_OI'])
            else:
                styled = df_opt.style.background_gradient(cmap='Greens', subset=['PE_OI'])
        st.dataframe(styled, use_container_width=True, height=600)
    else:
        st.warning("No option chain data available")
else:
    st.error("Failed to load any data. Please check your connection.")
