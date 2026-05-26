import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta
from scipy.stats import norm

st.set_page_config(page_title="Pro Options & Futures Terminal", layout="wide")

# -----------------------------------
# 1. RISK-FREE RATE (91-day T-bill) from RBI
# -----------------------------------
@st.cache_data(tttl=3600)  # update once per hour
def get_risk_free_rate():
    """
    Fetches latest 91-day T-bill yield from RBI's DBIE portal.
    Returns (rate_decimal, last_updated_date)
    """
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
    except Exception as e:
        st.warning(f"Could not fetch RBI rate: {e}. Using default 6.5%.")
        return 0.065, datetime.now().strftime("%Y-%m-%d")

# -----------------------------------
# 2. FETCH LIVE OPTION CHAIN (nselib)
# -----------------------------------
@st.cache_data(ttl=60)
def fetch_option_chain(symbol):
    try:
        import nselib
        data = nselib.derivatives.nse_live_option_chain(symbol=symbol)
        return data
    except Exception as e:
        st.error(f"Option chain fetch error: {e}")
        return None

# -----------------------------------
# 3. DEMO OPTION DATA (fallback)
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
    # Add change % columns
    df_opt['CE OI Change %'] = (df_opt['CE Change OI'] / df_opt['CE OI'].replace(0,1)) * 100
    df_opt['PE OI Change %'] = (df_opt['PE Change OI'] / df_opt['PE OI'].replace(0,1)) * 100
    return df_opt, spot

# -----------------------------------
# 4. GREEKS (simplified Black-Scholes)
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
    sigma = 0.15  # IV assumption
    df['CE Delta'], df['CE Gamma'] = zip(*df.apply(
        lambda row: calculate_greeks(spot, row['Strike'], T, r, sigma, 'CE'), axis=1
    ))
    df['PE Delta'], df['PE Gamma'] = zip(*df.apply(
        lambda row: calculate_greeks(spot, row['Strike'], T, r, sigma, 'PE'), axis=1
    ))
    return df

# -----------------------------------
# 5. MAX PAIN CALCULATION
# -----------------------------------
def calculate_max_pain(df):
    if df.empty:
        return 0
    strikes = df['Strike'].values
    pain = []
    for strike in strikes:
        total = 0
        for _, row in df.iterrows():
            s = row['Strike']
            ce_oi = row['CE OI']
            pe_oi = row['PE OI']
            if s <= strike:
                total += ce_oi * (strike - s)
            else:
                total += pe_oi * (s - strike)
        pain.append(total)
    return strikes[np.argmin(pain)]

# -----------------------------------
# 6. FUTURES FAIR VALUE (with dividend)
# -----------------------------------
def fetch_futures_bhavcopy(symbol):
    """
    Fetch futures data for a stock (e.g., 'SBIN') using nselib.
    Returns DataFrame with expiry, market price, etc.
    """
    try:
        import nselib
        # Use future_price_volume_data or futures_data – depends on library
        # We'll use a generic approach; adjust if needed
        df = nselib.derivatives.future_price_volume_data(
            symbol=symbol, instrument='FUTSTK',
            from_date=(datetime.now() - timedelta(days=30)).strftime('%d-%m-%Y'),
            to_date=datetime.now().strftime('%d-%m-%Y')
        )
        if df is not None and not df.empty:
            # Keep relevant columns: expiry, close price
            df = df.rename(columns={'EXPIRY_DT': 'Expiry', 'CLOSE': 'Market Future Price'})
            return df[['Expiry', 'Market Future Price']].drop_duplicates(subset='Expiry')
        return None
    except Exception as e:
        st.warning(f"Futures data fetch error: {e}")
        return None

def calculate_fair_prices(futures_df, spot_price, risk_free_rate, dividend_yield=0.0):
    """
    Compute fair future price using cost-of-carry model with dividends.
    Fair = Spot * exp((r - d) * t)
    """
    if futures_df is None or futures_df.empty:
        return pd.DataFrame()
    
    results = []
    today = datetime.now()
    for _, row in futures_df.iterrows():
        expiry = row['Expiry']
        if isinstance(expiry, str):
            expiry_date = datetime.strptime(expiry, '%d-%b-%Y')
        else:
            expiry_date = expiry
        if expiry_date.date() <= today.date():
            continue
        t = (expiry_date - today).days / 365.0
        market_price = row['Market Future Price']
        fair_price = spot_price * np.exp((risk_free_rate - dividend_yield) * t)
        basis = market_price - fair_price
        carry_pct = ((market_price - spot_price) / spot_price) * (365.0 / (t*365)) * 100 if t>0 else 0
        
        results.append({
            'Expiry': expiry_date.strftime('%d-%b-%Y'),
            'Spot Price': round(spot_price, 2),
            'Market Futures': round(market_price, 2),
            'Fair Futures': round(fair_price, 2),
            'Basis': round(basis, 2),
            'Annualised Carry %': round(carry_pct, 2),
            'Valuation': 'Undervalued' if market_price < fair_price else 'Overvalued'
        })
    return pd.DataFrame(results)

# -----------------------------------
# 7. MAIN UI
# -----------------------------------
st.title("📊 Institutional Derivatives Terminal")
st.markdown("Option Chain + Greeks + Max Pain + Futures Fair Valuation")

# Sidebar controls
symbol = st.sidebar.selectbox("Index for Options", ["NIFTY", "BANKNIFTY", "FINNIFTY"])
stock_for_futures = st.sidebar.text_input("Stock Symbol (e.g., SBIN, RELIANCE)", value="SBIN")
expected_dividend = st.sidebar.number_input("Expected Dividend Yield (%)", min_value=0.0, max_value=20.0, value=0.0, step=0.1) / 100.0
force_demo = st.sidebar.checkbox("Force Demo Mode", value=False)

if st.sidebar.button("Refresh All Data"):
    st.cache_data.clear()
    st.rerun()

# Fetch risk-free rate
risk_free_rate, rbi_date = get_risk_free_rate()
st.sidebar.caption(f"91-day T-bill rate: {risk_free_rate*100:.2f}% (as of {rbi_date})")

# ---------- OPTION CHAIN SECTION ----------
st.header(f"Option Chain – {symbol}")
live_data = None if force_demo else fetch_option_chain(symbol)

if live_data is not None and not live_data.empty:
    # Process live nselib data
    df_opt = live_data.copy()
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
    df_opt = df_opt.rename(columns={k:v for k,v in col_map.items() if k in df_opt.columns})
    # Compute change %
    df_opt['CE OI Change %'] = (df_opt['CE Change OI'] / df_opt['CE OI'].replace(0,1)) * 100
    df_opt['PE OI Change %'] = (df_opt['PE Change OI'] / df_opt['PE OI'].replace(0,1)) * 100
    # Approximate spot price (where CE LTP ≈ PE LTP)
    df_opt['diff'] = abs(df_opt['CE LTP'] - df_opt['PE LTP'])
    spot = df_opt.loc[df_opt['diff'].idxmin(), 'Strike'] if not df_opt.empty else 23500
    mode = "LIVE"
else:
    df_opt, spot = demo_option_data(symbol)
    mode = "DEMO"

# Add Greeks
df_opt = add_greeks(df_opt, spot, days_to_expiry=7)
max_pain = calculate_max_pain(df_opt)

# Metrics row
col1, col2, col3, col4 = st.columns(4)
pcr = df_opt['PE OI'].sum() / df_opt['CE OI'].sum() if df_opt['CE OI'].sum()>0 else 0
col1.metric("PCR (OI)", f"{pcr:.2f}")
col2.metric("Max Pain", f"₹{max_pain:,.0f}")
col3.metric("CE OI Total Change", f"{df_opt['CE Change OI'].sum():+,.0f}")
col4.metric("PE OI Total Change", f"{df_opt['PE Change OI'].sum():+,.0f}")

st.caption(f"Mode: {mode} | Spot approx: ₹{spot:,.0f}")

# Top OI strikes
st.subheader("🔑 Key OI Levels")
c1, c2 = st.columns(2)
with c1:
    st.write("**Highest CE OI (Resistance)**")
    st.dataframe(df_opt.nlargest(5, 'CE OI')[['Strike', 'CE OI', 'CE OI Change %']])
with c2:
    st.write("**Highest PE OI (Support)**")
    st.dataframe(df_opt.nlargest(5, 'PE OI')[['Strike', 'PE OI', 'PE OI Change %']])

# Full option chain
st.subheader("📈 Full Option Chain with Greeks")
display_cols = ['Strike', 'CE OI', 'CE OI Change %', 'CE Delta', 'CE Gamma',
                'PE OI', 'PE OI Change %', 'PE Delta', 'PE Gamma']
available = [c for c in display_cols if c in df_opt.columns]
st.dataframe(df_opt[available], use_container_width=True, height=500)

# CSV download
csv = df_opt[available].to_csv().encode('utf-8')
st.download_button("📥 Download Option Chain CSV", csv, "option_chain.csv", "text/csv")

# ---------- FUTURES FAIR VALUATION SECTION ----------
st.markdown("---")
st.header(f"Futures Fair Valuation – {stock_for_futures.upper()}")

# Fetch spot price for the stock (simple: try to get from nselib)
def get_spot_price(stock):
    try:
        import nselib
        df = nselib.capital_market.price_volume_data(symbol=stock, period='1D')
        if df is not None and not df.empty:
            return df['CLOSE'].iloc[-1]
    except:
        pass
    # fallback: prompt user
    return st.number_input(f"Enter current spot price for {stock.upper()}", value=1000.0, step=10.0)

stock_spot = get_spot_price(stock_for_futures)
if isinstance(stock_spot, float) and stock_spot > 0:
    st.write(f"Spot price (approx): ₹{stock_spot:,.2f}")
    futures_df = fetch_futures_bhavcopy(stock_for_futures.upper())
    if futures_df is not None and not futures_df.empty:
        fair_df = calculate_fair_prices(futures_df, stock_spot, risk_free_rate, dividend_yield=expected_dividend)
        if not fair_df.empty:
            st.dataframe(fair_df.style.format({
                'Spot Price': '₹{:.2f}',
                'Market Futures': '₹{:.2f}',
                'Fair Futures': '₹{:.2f}',
                'Basis': '₹{:.2f}',
                'Annualised Carry %': '{:.2f}%'
            }), use_container_width=True)
        else:
            st.warning("No valid futures contracts found.")
    else:
        st.warning(f"Could not fetch futures data for {stock_for_futures}. Ensure symbol is correct (e.g., SBIN, RELIANCE).")
else:
    st.info("Enter a valid spot price to compute fair values.")
