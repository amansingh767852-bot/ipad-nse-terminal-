import streamlit as st
import cloudscraper
import pandas as pd
from datetime import datetime
import time

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br"
}

@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    # This specifically bypasses the Cloudflare/Akamai firewall
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    
    base_url = "https://www.nseindia.com"
    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    fut_url = f"https://www.nseindia.com/api/liveEquity-derivatives?symbol={symbol}"
    
    try:
        # Step 1: Visit main site to generate human cookies
        scraper.get(base_url, headers=HEADERS, timeout=10)
        time.sleep(2) # Pause to act human
        
        # Step 2: Fetch the actual data
        oc_resp = scraper.get(oc_url, headers=HEADERS, timeout=10)
        fut_resp = scraper.get(fut_url, headers=HEADERS, timeout=10)
        
        if oc_resp.status_code == 200 and fut_resp.status_code == 200:
            return oc_resp.json(), fut_resp.json()
        return None, None
    except Exception:
        return None, None

def process_terminal(oc_json, fut_json):
    if not oc_json or not fut_json:
        return None, None, None
    
    try:
        # Process Options
        raw_oc = oc_json['records']['data']
        expiry = oc_json['records']['expiryDates'][0]
        
        opt_list = []
        for item in [x for x in raw_oc if x['expiryDate'] == expiry]:
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
        
        # Process 3 Expiry Futures
        fut_list = []
        for item in fut_json.get('data', []):
            if item.get('metadata', {}).get('instrumentType') in ['Index Futures', 'Stock Futures']:
                fut_list.append({
                    'Expiry': item.get('metadata', {}).get('expiryDate'),
                    'LTP': item.get('lastPrice', 0),
                    'Chg%': item.get('pChange', 0),
                    'OI': item.get('openInterest', 0),
                    'Chg_OI%': item.get('pchangeinOpenInterest', 0)
                })
        df_fut = pd.DataFrame(fut_list).head(3)
        
        total_ce = df_opt['CE_OI'].sum()
        total_pe = df_opt['PE_OI'].sum()
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        resistance = df_opt.loc[df_opt['CE_OI'].idxmax()]['Strike']
        support = df_opt.loc[df_opt['PE_OI'].idxmax()]['Strike']
        
        metrics = {
            'PCR': pcr,
            'Support': support,
            'Resistance': resistance,
            'Expiry': expiry,
            'Time': datetime.now().strftime("%H:%M:%S")
        }
        
        return df_opt, df_fut, metrics
    except Exception:
        return None, None, None

# --- UI DISPLAY ---
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear() # Clears bad data immediately

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
    st.error("NSE Firewall blocked the request. Please wait 5 seconds and click 'Refresh Data' again.")
