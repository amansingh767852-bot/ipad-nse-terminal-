import streamlit as st
import pandas as pd
from datetime import datetime
import time
import random

# Try to import curl_cffi, but fallback gracefully
try:
    from curl_cffi import requests as cffi_requests
    CFFI_AVAILABLE = True
except ImportError:
    CFFI_AVAILABLE = False
    st.warning("curl_cffi not installed. Install it with: pip install curl_cffi")

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# -------------------------------
# 1. DEMO DATA (used when real fetch fails)
# -------------------------------
def generate_demo_data(symbol):
    """Generate realistic fake data so your dashboard never looks empty"""
    base_strikes = [i for i in range(100, 301, 25)] if symbol == "NIFTY" else [i for i in range(4000, 6000, 100)]
    expiry = (datetime.now().replace(day=28) if datetime.now().day > 28 else datetime.now().replace(day=28)).strftime("%d-%b-%Y")
    
    opt_list = []
    for strike in base_strikes:
        # Fake OI with PCR ~1.2
        ce_oi = random.randint(50000, 500000)
        pe_oi = int(ce_oi * random.uniform(0.8, 1.5))
        opt_list.append({
            'CE_OI': ce_oi,
            'CE_Chg_OI': random.randint(-10000, 10000),
            'CE_LTP': round(random.uniform(10, 200), 1),
            'Strike': strike,
            'PE_LTP': round(random.uniform(10, 200), 1),
            'PE_Chg_OI': random.randint(-10000, 10000),
            'PE_OI': pe_oi
        })
    df_opt = pd.DataFrame(opt_list)
    
    fut_list = []
    for i in range(3):
        fut_list.append({
            'Expiry': f"{datetime.now().replace(day=28).strftime('%d-%b-%Y')}" if i==0 else f"{datetime.now().replace(month=datetime.now().month+1, day=28).strftime('%d-%b-%Y')}",
            'LTP': round(random.uniform(15000, 20000), 2),
            'Chg%': round(random.uniform(-1.5, 1.5), 2),
            'OI': random.randint(100000, 2000000),
            'Chg_OI%': round(random.uniform(-5, 5), 2)
        })
    df_fut = pd.DataFrame(fut_list)
    
    total_ce = df_opt['CE_OI'].sum()
    total_pe = df_opt['PE_OI'].sum()
    pcr = round(total_pe / total_ce, 2)
    resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike']
    support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike']
    
    metrics = {
        'PCR': pcr,
        'Support': support,
        'Resistance': resistance,
        'Expiry': expiry,
        'Time': datetime.now().strftime("%H:%M:%S"),
        'Mode': '🔹 DEMO MODE (real data blocked)'
    }
    return df_opt, df_fut, metrics

# -------------------------------
# 2. REAL FETCH WITH RETRIES & PROXY SUPPORT
# -------------------------------
def fetch_nse_data_real(symbol, proxy=None):
    """Try to fetch real data using curl_cffi or requests with proxy"""
    if not CFFI_AVAILABLE:
        return None, None
    
    base_url = "https://www.nseindia.com"
    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    fut_url = f"https://www.nseindia.com/api/liveEquity-derivatives?symbol={symbol}"
    
    for attempt in range(2):  # two attempts
        try:
            # Create session with impersonation
            session = cffi_requests.Session(impersonate="chrome120")
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}
            
            # First hit homepage
            session.get(base_url, headers=HEADERS, timeout=30)
            time.sleep(2)
            
            # Fetch data
            oc_resp = session.get(oc_url, headers=HEADERS, timeout=30)
            fut_resp = session.get(fut_url, headers=HEADERS, timeout=30)
            
            if oc_resp.status_code == 200 and fut_resp.status_code == 200:
                return oc_resp.json(), fut_resp.json()
            else:
                st.warning(f"Attempt {attempt+1}: HTTP {oc_resp.status_code}/{fut_resp.status_code}")
        except Exception as e:
            st.warning(f"Attempt {attempt+1} failed: {str(e)[:100]}")
            time.sleep(3)
    return None, None

# -------------------------------
# 3. PROCESS DATA (same as before)
# -------------------------------
def process_terminal(oc_json, fut_json):
    if not oc_json or not fut_json:
        return None, None, None
    
    try:
        raw_oc = oc_json['records']['data']
        expiry = oc_json['records']['expiryDates'][0]
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
        
        fut_list = []
        seen_exp = set()
        for item in fut_json.get('data', []):
            meta = item.get('metadata', {})
            if meta.get('instrumentType') in ['Index Futures', 'Stock Futures']:
                exp = meta.get('expiryDate')
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
        
        total_ce = df_opt['CE_OI'].sum()
        total_pe = df_opt['PE_OI'].sum()
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        
        metrics = {
            'PCR': pcr,
            'Support': support,
            'Resistance': resistance,
            'Expiry': expiry,
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Mode': '✅ LIVE DATA (real NSE)'
        }
        return df_opt, df_fut, metrics
    except Exception as e:
        st.error(f"Processing error: {e}")
        return None, None, None

# -------------------------------
# 4. MAIN UI
# -------------------------------
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

# Optional proxy input (for advanced users)
proxy = st.sidebar.text_input("Proxy (optional, e.g., http://user:pass@ip:port)", type="password")
use_demo = st.sidebar.checkbox("Force Demo Mode (skip real fetch)", value=False)

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()

# Fetch data (real or demo)
if use_demo:
    df_opt, df_fut, metrics = generate_demo_data(symbol)
else:
    oc_data, fut_data = fetch_nse_data_real(symbol, proxy=proxy if proxy else None)
    if oc_data and fut_data:
        df_opt, df_fut, metrics = process_terminal(oc_data, fut_data)
    else:
        st.warning("Real data fetch failed. Switching to DEMO MODE so dashboard works.")
        df_opt, df_fut, metrics = generate_demo_data(symbol)
        metrics['Mode'] = "⚠️ DEMO MODE (could not reach NSE)"

if metrics:
    st.info(metrics['Mode'])
    st.write(f"**Last Sync:** {metrics['Time']} | **Near Expiry:** {metrics['Expiry']}")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("PCR", metrics['PCR'])
    c2.metric("Support Wall", metrics['Support'])
    c3.metric("Resistance Wall", metrics['Resistance'])
    
    st.markdown("---")
    st.subheader("Combined Futures Flow (Next 3 Expiries)")
    st.dataframe(df_fut, use_container_width=True)
    
    st.subheader("Live Option Chain")
    st.dataframe(
        df_opt.style.background_gradient(cmap='Reds', subset=['CE_OI'])
                    .background_gradient(cmap='Greens', subset=['PE_OI']),
        use_container_width=True, height=600
    )
else:
    st.error("Unexpected error – please restart the app.")
