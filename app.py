import streamlit as st
import pandas as pd
from datetime import datetime
import time
import json
from curl_cffi import requests  # ← This library defeats Cloudflare/Akamai

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    """
    Fetches option chain and futures data using curl_cffi.
    It impersonates a real Chrome browser and uses a persistent session.
    """
    # Create a session that mimics Chrome 120
    session = requests.Session(impersonate="chrome120")
    
    base_url = "https://www.nseindia.com"
    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    fut_url = f"https://www.nseindia.com/api/liveEquity-derivatives?symbol={symbol}"
    
    try:
        # Step 1: Visit main page to get cookies and tokens
        session.get(base_url, headers=HEADERS, timeout=15)
        time.sleep(2)  # Act human
        
        # Step 2: Fetch option chain
        oc_resp = session.get(oc_url, headers=HEADERS, timeout=15)
        # Step 3: Fetch futures data
        fut_resp = session.get(fut_url, headers=HEADERS, timeout=15)
        
        if oc_resp.status_code == 200 and fut_resp.status_code == 200:
            return oc_resp.json(), fut_resp.json()
        else:
            st.warning(f"HTTP error: OC={oc_resp.status_code}, FUT={fut_resp.status_code}")
            return None, None
    except Exception as e:
        st.error(f"Request failed: {str(e)}")
        return None, None

def process_terminal(oc_json, fut_json):
    if not oc_json or not fut_json:
        return None, None, None
    
    try:
        # Process Options
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
        
        # Process Futures (first 3 unique expiries)
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
        
        # Calculate PCR, Support, Resistance
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
            'Time': datetime.now().strftime("%H:%M:%S")
        }
        
        return df_opt, df_fut, metrics
    except Exception as e:
        st.error(f"Processing error: {str(e)}")
        return None, None, None

# --- UI ---
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()

oc_data, fut_data = fetch_nse_data(symbol)
df_opt, df_fut, metrics = process_terminal(oc_data, fut_data)

if metrics:
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
    st.error("NSE is blocking the request. Wait 10 seconds and click 'Refresh Data' again. If it still fails, your IP might be temporarily banned – try a different network.")
