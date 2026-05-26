import streamlit as st
import pandas as pd
import numpy as np
import nselib
from datetime import datetime
from scipy.stats import norm

st.set_page_config(page_title="Pro Options Terminal", layout="wide")

# ---------- Greeks Approximation (simplified Black-Scholes) ----------
def calculate_greeks(S, K, T, r, sigma, option_type):
    """Calculate delta and gamma for a European option (approximation for index)."""
    if T <= 0 or sigma <= 0:
        return 0, 0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == 'CE':
        delta = norm.cdf(d1)
    else:  # PE
        delta = -norm.cdf(-d1)
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return delta, gamma

# ---------- Max Pain Calculation ----------
def calculate_max_pain(df_opt):
    """Compute Max Pain strike based on CE+PE OI."""
    if df_opt.empty:
        return 0
    strikes = df_opt['Strike'].values
    pain = []
    for strike in strikes:
        total_pain = 0
        for _, row in df_opt.iterrows():
            s = row['Strike']
            ce_oi = row['CE OI']
            pe_oi = row['PE OI']
            if s <= strike:
                total_pain += ce_oi * (strike - s)
            else:
                total_pain += pe_oi * (s - strike)
        pain.append(total_pain)
    max_pain_strike = strikes[np.argmin(pain)]
    return max_pain_strike

# ---------- Data Fetching ----------
@st.cache_data(ttl=60)
def fetch_nse_data(symbol):
    try:
        data = nselib.derivatives.nse_live_option_chain(symbol=symbol)
        # Also fetch spot price (approximate from first strike CE/PE LTP)
        return data
    except Exception as e:
        st.error(f"Live data error: {e}")
        return None

def generate_demo_data(symbol):
    """Demo data with realistic numbers."""
    np.random.seed(42)
    if symbol == "NIFTY":
        spot = 23500
        strikes = np.arange(22500, 24501, 100)
    elif symbol == "BANKNIFTY":
        spot = 49000
        strikes = np.arange(47000, 51001, 200)
    else:
        spot = 21000
        strikes = np.arange(20000, 22001, 100)
    
    rows = []
    for strike in strikes:
        # Simulate OI peaking near ATM
        distance = abs(strike - spot)
        ce_oi = max(50000, 500000 * np.exp(-distance/400))
        pe_oi = max(50000, 500000 * np.exp(-distance/400))
        rows.append({
            'Strike': strike,
            'CE OI': int(ce_oi),
            'CE LTP': max(0.1, np.random.uniform(1, 300)),
            'PE LTP': max(0.1, np.random.uniform(1, 300)),
            'PE OI': int(pe_oi),
            'CE Change OI': np.random.randint(-20000, 20000),
            'PE Change OI': np.random.randint(-20000, 20000),
        })
    df_opt = pd.DataFrame(rows)
    # Add calculated fields later
    return df_opt, spot

def process_live_data(data):
    if data is None or data.empty:
        return None, None
    try:
        df = data.copy()
        # Map columns
        col_map = {
            'strikePrice': 'Strike',
            'ce_openInterest': 'CE OI',
            'ce_lastPrice': 'CE LTP',
            'pe_lastPrice': 'PE LTP',
            'pe_openInterest': 'PE OI',
            'ce_changeinOpenInterest': 'CE Change OI',
            'pe_changeinOpenInterest': 'PE Change OI'
        }
        df = df.rename(columns={k:v for k,v in col_map.items() if k in df.columns})
        # Keep only needed columns
        keep = ['Strike', 'CE OI', 'CE LTP', 'PE LTP', 'PE OI', 'CE Change OI', 'PE Change OI']
        df = df[[c for c in keep if c in df.columns]]
        # Spot price: approximate using ATM strike where CE/PE LTP closest
        df['diff'] = abs(df['CE LTP'] - df['PE LTP'])
        spot_row = df.loc[df['diff'].idxmin()]
        spot = spot_row['Strike']
        return df, spot
    except Exception as e:
        st.error(f"Process error: {e}")
        return None, None

# ---------- Main UI ----------
st.title("📊 Pro Options Terminal – Max Pain, Greeks & Flow")

symbol = st.sidebar.selectbox("Index", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
refresh = st.sidebar.button("Refresh Data")

if refresh:
    st.cache_data.clear()

# Fetch data
raw_data = fetch_nse_data(symbol)
if raw_data is not None:
    df_opt, spot = process_live_data(raw_data)
    mode = "LIVE"
else:
    df_opt, spot = generate_demo_data(symbol)
    mode = "DEMO"

if df_opt is None or df_opt.empty:
    st.error("No data. Please try later.")
    st.stop()

# Calculate additional metrics
df_opt['Total OI'] = df_opt['CE OI'] + df_opt['PE OI']
df_opt['CE OI Change %'] = (df_opt['CE Change OI'] / df_opt['CE OI'].replace(0, 1)) * 100
df_opt['PE OI Change %'] = (df_opt['PE Change OI'] / df_opt['PE OI'].replace(0, 1)) * 100

# Greeks (simplified) – using approximate days to expiry (assuming 7 days left)
days_left = 7
T = days_left / 365
r = 0.065
sigma = 0.15  # 15% IV assumption – could be refined
S = spot

df_opt['CE Delta'], df_opt['CE Gamma'] = zip(*df_opt.apply(
    lambda row: calculate_greeks(S, row['Strike'], T, r, sigma, 'CE'), axis=1
))
df_opt['PE Delta'], df_opt['PE Gamma'] = zip(*df_opt.apply(
    lambda row: calculate_greeks(S, row['Strike'], T, r, sigma, 'PE'), axis=1
))

# Max Pain
max_pain = calculate_max_pain(df_opt)

# Total OI Change
total_ce_oi = df_opt['CE OI'].sum()
total_pe_oi = df_opt['PE OI'].sum()
total_ce_chg = df_opt['CE Change OI'].sum()
total_pe_chg = df_opt['PE Change OI'].sum()
pcr_oi = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi else 0

# Top CE & PE strikes
top_ce_strikes = df_opt.nlargest(5, 'CE OI')[['Strike', 'CE OI', 'CE OI Change %']]
top_pe_strikes = df_opt.nlargest(5, 'PE OI')[['Strike', 'PE OI', 'PE OI Change %']]

# ---------------- Display -----------------
st.header(f"{symbol} @ {spot:,.0f} ({mode} DATA)")

# Key metrics row
col1, col2, col3, col4 = st.columns(4)
col1.metric("PCR (OI)", pcr_oi)
col2.metric("Max Pain", f"₹{max_pain:,}")
col3.metric("CE OI Change (Total)", f"{total_ce_chg:+,}")
col4.metric("PE OI Change (Total)", f"{total_pe_chg:+,}")

st.markdown("---")

# Two columns: OI concentration
c_left, c_right = st.columns(2)
with c_left:
    st.subheader("🔥 Highest CE OI (Resistance)")
    st.dataframe(top_ce_strikes, use_container_width=True)
with c_right:
    st.subheader("🟢 Highest PE OI (Support)")
    st.dataframe(top_pe_strikes, use_container_width=True)

st.markdown("---")
st.subheader("📈 Full Option Chain with Greeks")
# Display select columns
display_cols = ['Strike', 'CE OI', 'CE OI Change %', 'CE Delta', 'CE Gamma',
                'PE OI', 'PE OI Change %', 'PE Delta', 'PE Gamma']
available = [c for c in display_cols if c in df_opt.columns]
st.dataframe(df_opt[available], use_container_width=True, height=500)

# Option to download
csv = df_opt[available].to_csv().encode('utf-8')
st.download_button("📥 Download Option Chain (CSV)", csv, "option_chain.csv", "text/csv")
