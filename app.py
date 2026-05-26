import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta
from scipy.stats import norm

st.set_page_config(page_title="Pro Derivatives Terminal", layout="wide")

# -----------------------------------
# 1. RISK-FREE RATE (91-day T-bill) from RBI
# -----------------------------------
@st.cache_data(ttl=3600)
def get_risk_free_rate():
    url = "https://api.rbi.org.in/api/v1/datasource/Series/Data/Filter?SeriesId=GsecFBIL.TBill.91.D"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        obs = data['Result']['Series'][0]['Observations'][-1]
        rate_percent = float(obs['Value'])
        rate_decimal = rate_percent / 100.0
        last_date = obs['TIMESTAMP']
        return rate_decimal, last_date
    except:
        return 0.065, datetime.now().strftime("%Y-%m-%d")

# -----------------------------------
# 2. FETCH LIVE OPTION CHAIN (nselib)
# -----------------------------------
@st.cache_data(ttl=60)
def fetch_option_chain(symbol):
    try:
        import nselib
        return nselib.derivatives.nse_live_option_chain(symbol=symbol)
    except:
        return None

# -----------------------------------
# 3. DEMO OPTION DATA
# -----------------------------------
def demo_option_data(symbol):
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
    df_opt['CE OI Change %'] = (df_opt['CE Change OI'] / df_opt['CE OI'].replace(0,1)) * 100
    df_opt['PE OI Change %'] = (df_opt['PE Change OI'] / df_opt['PE OI'].replace(0,1)) * 100
    return df_opt, spot

# -----------------------------------
# 4. GREEKS
# -----------------------------------
def calculate_greeks(S, K, T, r, sigma, opt_type):
    if T <= 0 or sigma <= 0:
        return 0, 0
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    if opt_type == 'CE':
        delta = norm.cdf(d1)
    else:
        delta = -norm.cdf(-d1)
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return delta, gamma

def add_greeks(df, spot, days_to_expiry=7):
    T = days_to_expiry / 365.0
    r, _ = get_risk_free_rate()
    sigma = 0.15
    df['CE Delta'], df['CE Gamma'] = zip(*df.apply(
        lambda row: calculate_greeks(spot, row['Strike'], T, r, sigma, 'CE'), axis=1))
    df['PE Delta'], df['PE Gamma'] = zip(*df.apply(
        lambda row: calculate_greeks(spot, row['Strike'], T, r, sigma, 'PE'), axis=1))
    return df

def calculate_max_pain(df):
    if df.empty:
        return 0
    strikes = df['Strike'].values
    pain = []
    for strike in strikes:
        total = 0
        for _, row in df.iterrows():
            s = row['Strike']
            if s <= strike:
                total += row['CE OI'] * (strike - s)
            else:
                total += row['PE OI'] * (s - strike)
        pain.append(total)
    return strikes[np.argmin(pain)]

# -----------------------------------
# 5. OI SENTIMENT SCORE (New)
# -----------------------------------
def oi_sentiment_score(df):
    total_ce_change = df['CE Change OI'].sum()
    total_pe_change = df['PE Change OI'].sum()
    if abs(total_ce_change) + abs(total_pe_change) == 0:
        return "Neutral", 0
    # Score >0 => bullish (PE change dominates)
    # Score <0 => bearish (CE change dominates)
    score = (total_pe_change - total_ce_change) / (abs(total_ce_change) + abs(total_pe_change))
    if score > 0.2:
        sentiment = "🟢 Bullish (Put writers active) – Expect upward move"
    elif score < -0.2:
        sentiment = "🔴 Bearish (Call writers active) – Expect downward move"
    else:
        sentiment = "⚪ Neutral – No clear OI bias"
    return sentiment, score

# -----------------------------------
# 6. GAP-UP / GAP-DOWN SCANNER (using nselib equity data)
# -----------------------------------
@st.cache_data(ttl=3600)
def get_prev_day_data(symbol):
    """Fetch yesterday's open, high, low, close for a stock."""
    try:
        import nselib
        # Get last 2 days of equity data
        df = nselib.capital_market.price_volume_data(symbol=symbol, period='1W')
        if df is not None and not df.empty:
            # Sort by date and take the last completed day (not today if intraday)
            df['DATE'] = pd.to_datetime(df['TIMESTAMP'])
            df = df.sort_values('DATE')
            last_complete = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
            return {
                'open': last_complete['OPEN'],
                'high': last_complete['HIGH'],
                'low': last_complete['LOW'],
                'close': last_complete['CLOSE'],
                'date': last_complete['DATE'].date()
            }
    except:
        pass
    return None

def gap_analysis(symbol, current_price=None):
    prev = get_prev_day_data(symbol)
    if not prev:
        return None, "Data not available"
    # If current_price not given, try to fetch live price (simplified: use last close)
    if current_price is None:
        current_price = prev['close']  # placeholder; in live you'd use real-time
    gap_up = current_price > prev['high']
    gap_down = current_price < prev['low']
    if gap_up:
        status = f"🚀 Gap Up (open > yesterday high {prev['high']}) – Bullish bias"
    elif gap_down:
        status = f"📉 Gap Down (open < yesterday low {prev['low']}) – Bearish bias"
    else:
        status = f"⏺ No Gap (within yesterday range {prev['low']} - {prev['high']})"
    return prev, status

# -----------------------------------
# 7. FUTURES FAIR VALUE
# -----------------------------------
def fetch_futures_bhavcopy(symbol):
    try:
        import nselib
        df = nselib.derivatives.future_price_volume_data(
            symbol=symbol, instrument='FUTSTK',
            from_date=(datetime.now() - timedelta(days=30)).strftime('%d-%m-%Y'),
            to_date=datetime.now().strftime('%d-%m-%Y')
        )
        if df is not None and not df.empty:
            df = df.rename(columns={'EXPIRY_DT': 'Expiry', 'CLOSE': 'Market Future Price'})
            return df[['Expiry', 'Market Future Price']].drop_duplicates(subset='Expiry')
    except:
        pass
    return None

def calculate_fair_prices(futures_df, spot_price, risk_free_rate, dividend_yield=0.0):
    if futures_df is None or futures_df.empty:
        return pd.DataFrame()
    results = []
    today = datetime.now()
    for _, row in futures_df.iterrows():
        expiry = row['Expiry']
        expiry_date = datetime.strptime(expiry, '%d-%b-%Y') if isinstance(expiry, str) else expiry
        if expiry_date.date() <= today.date():
            continue
        t = (expiry_date - today).days / 365.0
        market_price = row['Market Future Price']
        fair_price = spot_price * np.exp((risk_free_rate - dividend_yield) * t)
        basis = market_price - fair_price
        carry_pct = ((market_price - spot_price)/spot_price)*(365.0/(t*365))*100 if t>0 else 0
        results.append({
            'Expiry': expiry_date.strftime('%d-%b-%Y'),
            'Market Futures': round(market_price, 2),
            'Fair Futures': round(fair_price, 2),
            'Basis': round(basis, 2),
            'Carry %': round(carry_pct, 2),
            'Valuation': 'Undervalued' if market_price < fair_price else 'Overvalued'
        })
    return pd.DataFrame(results)

# -----------------------------------
# 8. MAIN UI
# -----------------------------------
st.title("📊 Institutional Derivatives Terminal")
st.markdown("Option Chain | OI Sentiment | Gap Scanner | Futures Fair Price")

# Sidebar
symbol = st.sidebar.selectbox("Index for Options", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
stock_scanner = st.sidebar.text_input("Stock for Gap Analysis & OI S/R", value="SBIN")
stock_spot = st.sidebar.number_input(f"Current Spot Price ({stock_scanner})", value=1000.0, step=10.0, format="%.2f")
expected_dividend = st.sidebar.number_input("Dividend Yield (%) for Futures", min_value=0.0, max_value=20.0, value=0.0, step=0.1) / 100.0
force_demo = st.sidebar.checkbox("Force Demo Mode", value=False)

if st.sidebar.button("Refresh All"):
    st.cache_data.clear()
    st.rerun()

# Risk-free rate
risk_free_rate, rbi_date = get_risk_free_rate()
st.sidebar.caption(f"91-day T-bill: {risk_free_rate*100:.2f}% (RBI {rbi_date})")

# ---------- OPTION CHAIN SECTION ----------
st.header(f"Option Chain – {symbol}")
live_opt = None if force_demo else fetch_option_chain(symbol)

if live_opt is not None and not live_opt.empty:
    df_opt = live_opt.copy()
    col_map = {
        'strikePrice': 'Strike',
        'ce_openInterest': 'CE OI',
        'ce_lastPrice': 'CE LTP',
        'pe_lastPrice': 'PE LTP',
        'pe_openInterest': 'PE OI',
        'ce_changeinOpenInterest': 'CE Change OI',
        'pe_changeinOpenInterest': 'PE Change OI'
    }
    df_opt = df_opt.rename(columns={k:v for k,v in col_map.items() if k in df_opt.columns})
    df_opt['CE OI Change %'] = (df_opt['CE Change OI'] / df_opt['CE OI'].replace(0,1)) * 100
    df_opt['PE OI Change %'] = (df_opt['PE Change OI'] / df_opt['PE OI'].replace(0,1)) * 100
    df_opt['diff'] = abs(df_opt['CE LTP'] - df_opt['PE LTP'])
    spot_index = df_opt.loc[df_opt['diff'].idxmin(), 'Strike'] if not df_opt.empty else 23500
    mode = "LIVE"
else:
    df_opt, spot_index = demo_option_data(symbol)
    mode = "DEMO"

# Add Greeks and metrics
df_opt = add_greeks(df_opt, spot_index)
max_pain = calculate_max_pain(df_opt)
sentiment, sent_score = oi_sentiment_score(df_opt)

# Display OI Sentiment Score prominently
st.subheader("🧠 Market Sentiment (OI Flow)")
st.metric("OI Sentiment Score", f"{sent_score:.2f}", delta=sentiment if sent_score>0.1 else None)
st.info(f"{sentiment}")

# Top OI levels
col1, col2 = st.columns(2)
with col1:
    st.subheader("🔥 Resistance (Highest CE OI)")
    st.dataframe(df_opt.nlargest(5, 'CE OI')[['Strike', 'CE OI', 'CE OI Change %']])
with col2:
    st.subheader("🟢 Support (Highest PE OI)")
    st.dataframe(df_opt.nlargest(5, 'PE OI')[['Strike', 'PE OI', 'PE OI Change %']])

# Metrics row
colA, colB, colC, colD = st.columns(4)
pcr = df_opt['PE OI'].sum() / df_opt['CE OI'].sum() if df_opt['CE OI'].sum()>0 else 0
colA.metric("PCR (OI)", f"{pcr:.2f}")
colB.metric("Max Pain", f"₹{max_pain:,.0f}")
colC.metric("CE OI Δ", f"{df_opt['CE Change OI'].sum():+,.0f}")
colD.metric("PE OI Δ", f"{df_opt['PE Change OI'].sum():+,.0f}")

st.caption(f"Mode: {mode} | Spot approx: ₹{spot_index:,.0f}")

# Full option chain
with st.expander("📋 Full Option Chain with Greeks"):
    display_cols = ['Strike', 'CE OI', 'CE OI Change %', 'CE Delta', 'CE Gamma',
                    'PE OI', 'PE OI Change %', 'PE Delta', 'PE Gamma']
    available = [c for c in display_cols if c in df_opt.columns]
    st.dataframe(df_opt[available], use_container_width=True, height=500)
    csv = df_opt[available].to_csv().encode('utf-8')
    st.download_button("📥 Download CSV", csv, "option_chain.csv", "text/csv")

# ---------- STOCK SPECIFIC ANALYSIS (Gap + OI Support/Resistance) ----------
st.markdown("---")
st.header(f"Stock Analysis: {stock_scanner.upper()}")

# Gap-up/down analysis
prev_data, gap_status = gap_analysis(stock_scanner, stock_spot)
if prev_data:
    st.subheader("Gap & Range")
    st.write(f"**Yesterday:** Open {prev_data['open']} | High {prev_data['high']} | Low {prev_data['low']} | Close {prev_data['close']}")
    st.write(gap_status)
else:
    st.warning("Could not fetch historical data for this stock. Ensure symbol is correct (e.g., SBIN, RELIANCE).")

# Option chain for the stock (if available) – we can fetch stock's option OI for S/R
st.subheader("Option OI Based Support/Resistance")
stock_opt_symbol = f"{stock_scanner.upper()}EQ"  # nselib expects something like 'SBINEQ'
try:
    import nselib
    stock_opt_data = nselib.derivatives.nse_live_option_chain(symbol=stock_opt_symbol)
    if stock_opt_data is not None and not stock_opt_data.empty:
        # Process similarly
        df_stock_opt = stock_opt_data.rename(columns={
            'strikePrice': 'Strike',
            'ce_openInterest': 'CE OI',
            'pe_openInterest': 'PE OI'
        })
        top_ce = df_stock_opt.nlargest(3, 'CE OI')[['Strike', 'CE OI']]
        top_pe = df_stock_opt.nlargest(3, 'PE OI')[['Strike', 'PE OI']]
        colA, colB = st.columns(2)
        with colA:
            st.write("**Resistance (CE OI)**")
            st.dataframe(top_ce)
        with colB:
            st.write("**Support (PE OI)**")
            st.dataframe(top_pe)
    else:
        st.info("No option chain data for this stock. Possibly not in F&O or market closed.")
except:
    st.info("Option chain not available for this stock (may not be F&O or market closed).")

# ---------- FUTURES FAIR VALUATION ----------
st.subheader("Futures Fair Valuation (Cost of Carry)")
futures_df = fetch_futures_bhavcopy(stock_scanner.upper())
if futures_df is not None and not futures_df.empty:
    fair_df = calculate_fair_prices(futures_df, stock_spot, risk_free_rate, expected_dividend)
    if not fair_df.empty:
        st.dataframe(fair_df.style.format({
            'Market Futures': '₹{:.2f}',
            'Fair Futures': '₹{:.2f}',
            'Basis': '₹{:.2f}',
            'Carry %': '{:.2f}%'
        }), use_container_width=True)
    else:
        st.warning("No valid futures contracts found.")
else:
    st.warning(f"No futures data for {stock_scanner}. Check symbol (e.g., SBIN, HDFC).")
