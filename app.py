import streamlit as st
import requests
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br'
}

@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    session = requests.Session()
    base_url = "https://www.nseindia.com"
    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    fut_url = f"https://www.nseindia.com/api/liveEquity-derivatives?symbol={symbol}"
    
    try:
        session.get(base_url, headers=HEADERS, timeout=10)
        
        # Get Option Chain
        oc_resp = session.get(oc_url, headers=HEADERS, timeout=10)
        oc_data = oc_resp.json() if oc_resp.status_code == 200 else None
        
        # Get Futures
        fut_resp = session.get(fut_url, headers=HEADERS, timeout=10)
        fut_data = fut_resp.json() if fut_resp.status_code == 200 else None
        
        return oc_data, fut_data
    except Exception:
        return None, None

def process_terminal(oc_json, fut_json):
    if not oc_json or not fut_json:
        return None, None, None
    
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

# --- UI DISPLAY ---
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
st.sidebar.button("Refresh Data")

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
    st.error("Attempting to bypass NSE block... Click 'Refresh Data' in 5 seconds.")
