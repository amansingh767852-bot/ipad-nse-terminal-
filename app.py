import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import time
import logging
from pathlib import Path
import requests
import zipfile
import io

st.set_page_config(page_title="Institutional Derivatives Terminal", layout="wide")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@st.cache_data(ttl=86400)
def get_previous_trading_day():
    """Calculate the most recent previous trading day (assuming holidays are ignored)."""
    today = datetime.now()
    # Days offset: 1 for Monday-Friday, 3 for Monday (to skip Sat/Sun)
    # Simple logic: go back 1 day, if it's Saturday go back 2 days, if Sunday go back 1 more day.
    delta = 1
    if today.weekday() == 6:  # Sunday
        delta = 2
    elif today.weekday() == 0:  # Monday
        delta = 3
    prev_day = today - timedelta(days=delta)
    return prev_day

def fetch_last_eod_data(symbol):
    """
    Downloads the latest available F&O bhavcopy and extracts the option chain for the given symbol.
    """
    try:
        from nse import NSE
        download_folder = Path("./nse_cache")
        download_folder.mkdir(exist_ok=True)
        
        with NSE(download_folder=download_folder, server=True) as nse:
            # Get the most recent previous trading day
            last_trading_day = get_previous_trading_day()
            
            # Download the F&O bhavcopy for that day
            bhavcopy_path = nse.fnoBhavcopy(date=last_trading_day, folder=download_folder)
            if not bhavcopy_path:
                return None
                
            # The bhavcopy is a zip file containing CSV files.
            # We need to find the specific file containing the option chain for our symbol.
            # Based on the NSE format, the file name will be like "op<ddmmyy>.csv"
            # Search for the correct file.
            import csv
            with zipfile.ZipFile(bhavcopy_path, 'r') as zip_ref:
                for file_name in zip_ref.namelist():
                    if file_name.lower().endswith('.csv'):
                        with zip_ref.open(file_name) as csv_file:
                            # Decode bytes to string and create a CSV reader
                            text_stream = io.TextIOWrapper(csv_file, encoding='utf-8')
                            reader = csv.DictReader(text_stream)
                            data = list(reader)
                            # Check if this file contains data for our symbol
                            # The symbol in the csv might be in a column like 'SYMBOL' or 'UNDERLYING'
                            if data and any(row.get('SYMBOL') == symbol or row.get('UNDERLYING') == symbol for row in data):
                                return data
            return None
    except Exception as e:
        st.warning(f"Could not fetch EOD data: {str(e)}")
        return None

def generate_closing_data_from_eod(raw_data, symbol):
    """
    Convert the raw EOD data into the DataFrame format expected by the app.
    """
    try:
        if not raw_data:
            return None, None, None
        
        # The raw_data is a list of dictionaries from the CSV.
        # We need to filter for the correct expiry and aggregate per strike.
        # This is a simplified transformation; you may need to adjust based on actual CSV structure.
        # Common columns: STRIKE_PR, OPTION_TYPE, OPEN_INT, CHG_IN_OI, CLOSE, etc.
        opt_list = []
        for row in raw_data:
            # Filter for relevant rows based on symbol and option type (CE/PE)
            # This is a placeholder; actual parsing requires inspection of the CSV structure.
            strike = row.get('STRIKE_PR')
            opt_type = row.get('OPTION_TYPE')
            if opt_type == 'CE':
                opt_list.append({
                    'CE OI': int(row.get('OPEN_INT', 0)),
                    'CE Chg OI': int(row.get('CHG_IN_OI', 0)),
                    'CE LTP': float(row.get('CLOSE', 0)),
                    'Strike': strike,
                    'PE LTP': 0,  # Placeholder
                    'PE Chg OI': 0,
                    'PE OI': 0
                })
            elif opt_type == 'PE':
                opt_list.append({
                    'CE OI': 0,
                    'CE Chg OI': 0,
                    'CE LTP': 0,
                    'Strike': strike,
                    'PE LTP': float(row.get('CLOSE', 0)),
                    'PE Chg OI': int(row.get('CHG_IN_OI', 0)),
                    'PE OI': int(row.get('OPEN_INT', 0))
                })
        
        # Combine CE and PE data for each strike (if needed)
        df_opt = pd.DataFrame(opt_list)
        # If there are separate rows for CE and PE, you may need to pivot or merge.
        # For now, assume the CSV contains separate rows.
        # Aggregate by strike
        if not df_opt.empty:
            df_opt = df_opt.groupby('Strike').sum().reset_index()
        
        # Create a simple futures placeholder
        expiry = datetime.now().strftime("%d-%b-%Y")
        df_fut = pd.DataFrame([
            {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg OI%': 0},
            {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg OI%': 0},
            {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg OI%': 0}
        ])
        
        total_ce = df_opt['CE OI'].sum()
        total_pe = df_opt['PE OI'].sum()
        pcr = round(total_pe / total_ce, 2) if total_ce else 1.2
        resistance = df_opt.loc[df_opt['CE OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        support = df_opt.loc[df_opt['PE OI'].idxmax()]['Strike'] if not df_opt.empty else 0
        
        metrics = {
            'PCR': pcr,
            'Support': support,
            'Resistance': resistance,
            'Expiry': expiry,
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Mode': "🔹 EOD DATA (last closing data)"
        }
        return df_opt, df_fut, metrics
    except Exception as e:
        st.error(f"Error processing EOD data: {str(e)}")
        return None, None, None

def fetch_live_data(symbol):
    """Try to fetch real-time data from NSE (works during market hours)."""
    try:
        from nse import NSE
        download_folder = Path("./nse_cache")
        download_folder.mkdir(exist_ok=True)
        with NSE(download_folder=download_folder, server=True) as nse:
            # Fetch live option chain
            oc_data = nse.optionchain(symbol=symbol.lower())
            if oc_data and 'records' in oc_data and oc_data['records'].get('data'):
                return oc_data
            return None
    except Exception as e:
        st.warning(f"Live data not available: {str(e)}")
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
            'CE OI': ce.get('openInterest', 0),
            'CE Chg OI': ce.get('changeinOpenInterest', 0),
            'CE LTP': ce.get('lastPrice', 0),
            'Strike': strike,
            'PE LTP': pe.get('lastPrice', 0),
            'PE Chg OI': pe.get('changeinOpenInterest', 0),
            'PE OI': pe.get('openInterest', 0)
        })
    df_opt = pd.DataFrame(opt_list)
    
    # Futures placeholder
    df_fut = pd.DataFrame([
        {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg OI%': 0},
        {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg OI%': 0},
        {'Expiry': expiry, 'LTP': 0, 'Chg%': 0, 'OI': 0, 'Chg OI%': 0}
    ])
    
    total_ce = df_opt['CE OI'].sum()
    total_pe = df_opt['PE OI'].sum()
    pcr = round(total_pe / total_ce, 2) if total_ce else 0
    resistance = df_opt.loc[df_opt['CE OI'].idxmax()]['Strike'] if not df_opt.empty else 0
    support = df_opt.loc[df_opt['PE OI'].idxmax()]['Strike'] if not df_opt.empty else 0
    
    metrics = {
        'PCR': pcr,
        'Support': support,
        'Resistance': resistance,
        'Expiry': expiry,
        'Time': datetime.now().strftime("%H:%M:%S"),
        'Mode': "✅ LIVE DATA (real-time)"
    }
    return df_opt, df_fut, metrics

# ------------------- UI -------------------
st.title("Live NSE Terminal: Option Chain & Futures")

symbol = st.sidebar.selectbox("Select Asset", ["NIFTY", "BANKNIFTY", "FINNIFTY"])

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Fetch data: try live first, then fallback to EOD
live_data = fetch_live_data(symbol)
if live_data:
    df_opt, df_fut, metrics = process_live_data(live_data, symbol)
else:
    eod_data = fetch_last_eod_data(symbol)
    if eod_data:
        df_opt, df_fut, metrics = generate_closing_data_from_eod(eod_data, symbol)
    else:
        st.error("Unable to fetch any data. Please check your connection or try again later.")
        st.stop()

# Display
if metrics:
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
        st.dataframe(df_opt, use_container_width=True, height=600)
    else:
        st.warning("No option chain data available")
else:
    st.error("Failed to load any data. Please check your connection.")
