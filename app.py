import streamlit as st
import requests
from datetime import datetime, time as dtime, timedelta
import time
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from pytz import timezone

# ================== TIMEZONE SETUP ==================
IST = timezone('Asia/Kolkata')

def get_ist_time():
    """Get current time in IST (UTC+5:30)"""
    return datetime.now(IST)

# ================== PAGE CONFIG ==================
st.set_page_config(
    page_title="NIFTY ΔOI PCR Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ================== GLOBAL CSS ==================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville&display=swap');

html, body, [class*="css"] {
    font-family: 'Libre+Baskerville', serif;
}

@keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.5; }
    100% { opacity: 1; }
}

.pulse {
    animation: pulse 2s infinite;
}

.status-badge {
    padding: 6px 12px;
    border-radius: 20px;
    font-weight: bold;
    display: inline-block;
}

.live-badge {
    background: linear-gradient(90deg, #2ecc71, #27ae60);
    animation: pulse 2s infinite;
}

.after-market-badge {
    background: linear-gradient(90deg, #e74c3c, #c0392b);
}
</style>
""", unsafe_allow_html=True)

# ================== UTILITIES ==================
def log(msg, level="INFO"):
    timestamp = get_ist_time()
    st.session_state.logs.append({
        "time": timestamp,
        "level": level,
        "message": msg
    })

def market_status():
    """Check market status in IST timezone"""
    ist_time = get_ist_time()
    now = ist_time.time()
    
    # Market hours in IST: 9:15 AM to 3:30 PM
    market_open = dtime(9, 15)
    market_close = dtime(15, 30)
    
    is_market_hours = market_open <= now <= market_close
    
    # Check if today is Tuesday (weekly expiry day for NIFTY)
    is_tuesday = ist_time.weekday() == 1  # Monday=0, Tuesday=1
    
    if is_market_hours:
        return {
            "status": "LIVE",
            "color": "#2ecc71",
            "icon": "🟢",
            "is_tuesday": is_tuesday
        }
    else:
        return {
            "status": "AFTER_MARKET",
            "color": "#e74c3c",
            "icon": "🔴",
            "is_tuesday": is_tuesday
        }

def strike_range_by_dte(dte):
    if dte >= 7:
        return 7
    if 4 <= dte <= 6:
        return 5
    if 2 <= dte <= 3:
        return 3
    return 1

# ================== ALTERNATIVE DATA SOURCES ==================
def fetch_nse_option_data():
    """
    Try multiple endpoints to fetch NSE option chain data
    Returns: tuple of (data_dict, error_message)
    """
    endpoints = [
        {
            "name": "NSE India Official",
            "url": "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Referer": "https://www.nseindia.com/get-quotes/derivatives?symbol=NIFTY",
                "Origin": "https://www.nseindia.com",
                "DNT": "1"
            }
        },
        {
            "name": "Trendlyne API",
            "url": "https://api.trendlyne.com/v1/options/nifty",
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            }
        },
        {
            "name": "Sensibull Alternative",
            "url": "https://webapi.sensibull.com/v1/option_chain?tradingsymbol=NIFTY",
            "headers": {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json"
            }
        }
    ]
    
    for endpoint in endpoints:
        try:
            response = requests.get(
                endpoint["url"], 
                headers=endpoint["headers"],
                timeout=10
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    log(f"Successfully fetched data from {endpoint['name']}", "INFO")
                    return data, None
                except:
                    continue
        except:
            continue
    
    return None, "All API endpoints failed"

def fetch_pcr(base_strike, dte, manual_range):
    """Fetch PCR data with fallback options"""
    try:
        # Try to get data from any available source
        raw_data, error = fetch_nse_option_data()
        
        if raw_data is None:
            return None, f"Data fetch failed: {error}"
        
        # Parse the data based on source
        if "records" in raw_data:
            # NSE format
            records = raw_data["records"]["data"]
            spot = raw_data["records"]["underlyingValue"]
            timestamp = raw_data["records"].get("timestamp", "")
        elif "optionChain" in raw_data:
            # Alternative format 1
            records = raw_data["optionChain"]["data"]
            spot = raw_data["optionChain"]["underlyingValue"]
            timestamp = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        else:
            # Try to find data in different structures
            records = raw_data.get("data", [])
            spot = raw_data.get("underlyingValue", 22000)
            timestamp = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        
        if not records:
            return None, "No option chain data found"
        
        rng = manual_range if manual_range is not None else strike_range_by_dte(dte)
        strikes = [base_strike + i * 50 for i in range(-rng, rng + 1)]
        
        put_doi, call_doi = 0, 0
        
        for row in records:
            strike_price = row.get("strikePrice", row.get("strike", 0))
            if strike_price in strikes:
                # Try different key names for put data
                pe_data = None
                if "PE" in row:
                    pe_data = row["PE"]
                elif "put" in row:
                    pe_data = row["put"]
                
                # Try different key names for call data
                ce_data = None
                if "CE" in row:
                    ce_data = row["CE"]
                elif "call" in row:
                    ce_data = row["call"]
                
                if pe_data:
                    # Try different key names for changeinOpenInterest
                    put_doi += pe_data.get("changeinOpenInterest", 
                                          pe_data.get("change_in_oi", 
                                                     pe_data.get("oi_change", 0)))
                
                if ce_data:
                    call_doi += ce_data.get("changeinOpenInterest", 
                                           ce_data.get("change_in_oi", 
                                                      ce_data.get("oi_change", 0)))
        
        if call_doi == 0:
            # If call ΔOI is 0, set PCR to 0 or use fallback
            pcr_value = 0
        else:
            pcr_value = put_doi / call_doi
        
        return {
            "time": get_ist_time(),
            "timestamp": timestamp,
            "pcr": round(pcr_value, 2),
            "put_doi": put_doi,
            "call_doi": call_doi,
            "spot": spot,
            "strikes": rng
        }, "OK"
        
    except Exception as e:
        # Fallback to mock data for demonstration
        return get_mock_data(base_strike, dte, manual_range), f"Using mock data: {str(e)}"

def get_mock_data(base_strike, dte, manual_range):
    """Generate realistic mock data for demonstration"""
    ist_time = get_ist_time()
    rng = manual_range if manual_range is not None else strike_range_by_dte(dte)
    
    # Simulate realistic market movements
    hour = ist_time.hour
    minute = ist_time.minute
    
    # Base values that change throughout the day
    base_spot = 22000
    spot_variation = np.sin(hour + minute/60) * 100
    spot = base_spot + spot_variation
    
    # PCR follows a pattern
    base_pcr = 1.2
    pcr_variation = np.sin((hour * 60 + minute) / 180) * 0.3  # 3-hour cycle
    pcr = base_pcr + pcr_variation
    
    # ΔOI values
    put_doi = int(1000000 + np.random.randn() * 200000)
    call_doi = int(put_doi / pcr)
    
    return {
        "time": ist_time,
        "timestamp": ist_time.strftime("%d-%b-%Y %H:%M:%S"),
        "pcr": round(pcr, 2),
        "put_doi": put_doi,
        "call_doi": call_doi,
        "spot": round(spot, 2),
        "strikes": rng,
        "is_mock": True
    }

def pcr_trade_signal(pcr):
    if pcr < 0.75:
        return "PUT", "🔴 Bearish Bias - Put Writing Dominant", "error", "#e74c3c"
    elif 0.75 <= pcr <= 1.25:
        return "NEUTRAL", "⚪ Neutral Zone - Caution Advised", "warning", "#f1c40f"
    else:
        return "CALL", "🟢 Bullish Bias - Strong Put Addition", "success", "#2ecc71"

# ================== SESSION STATE ==================
if "session" not in st.session_state:
    st.session_state.logs = []
    st.session_state.data_history = []
    st.session_state.last_valid = None
    st.session_state.last_refresh = None
    st.session_state.refresh_count = 0
    st.session_state.use_mock_data = False

# ================== SIDEBAR ==================
with st.sidebar:
    st.title("⚙️ Control Panel")
    
    # Market Status
    status_info = market_status()
    badge_class = "live-badge" if status_info['status'] == 'LIVE' else "after-market-badge"
    badge_icon = "🟢" if status_info['status'] == 'LIVE' else "🔴"
    
    st.markdown(f"""
    <div style="background:#1c1f26; padding:15px; border-radius:10px; margin-bottom:15px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <div>
                <h4 style="margin:0;">Market Status</h4>
                <p style="margin:3px 0 0 0; font-size:12px; color:#95a5a6;">
                    {get_ist_time().strftime('%d %b %Y')}
                </p>
            </div>
            <span class="status-badge {badge_class}">
                {badge_icon} {status_info['status']}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Tuesday Warning
    if status_info['is_tuesday']:
        st.error("⚠️ **TODAY IS EXPIRY DAY** - NO TRADES ALLOWED!", icon="⚠️")
    
    st.markdown("---")
    
    # Data Source Selection
    st.subheader("📡 Data Source")
    use_mock = st.checkbox("Use Demo Data", value=False, 
                          help="Use simulated data if live data fails")
    if use_mock:
        st.info("Using simulated data for demonstration")
    
    # Parameters
    base_strike = st.number_input(
        "🎯 Base Strike Price",
        min_value=10000,
        max_value=50000,
        step=50,
        value=22500,
        help="ATM (At The Money) strike price"
    )
    
    col1, col2 = st.columns(2)
    with col1:
        dte = st.slider("📅 DTE", 0, 10, 3, help="Days to Expiry")
    with col2:
        manual_range = st.selectbox("🎯 Range", [None, 1, 2, 3, 4, 5, 7], index=0)
    
    st.markdown("---")
    
    # Refresh Controls
    st.subheader("🔄 Refresh Settings")
    
    auto_refresh = st.toggle("Auto Refresh", value=True)
    
    if auto_refresh:
        refresh_interval = st.select_slider(
            "Refresh Interval",
            options=[30, 60, 120, 180, 300],
            value=180,
            help="NSE updates every 3 minutes"
        )
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Refresh Now", use_container_width=True):
            st.session_state.refresh_count += 1
            st.rerun()
    
    # Data Stats
    if st.session_state.data_history:
        st.markdown("---")
        st.subheader("📊 Session Stats")
        total_data = len(st.session_state.data_history)
        if st.session_state.data_history:
            last_update = st.session_state.data_history[-1]["time"].strftime("%H:%M:%S")
            st.metric("Data Points", total_data)
            st.metric("Last Update", last_update)

# ================== MAIN DASHBOARD ==================
# Header with animated status sphere
status_info = market_status()
current_time = get_ist_time()
sphere_color = "#2ecc71" if status_info['status'] == 'LIVE' else "#e74c3c"

st.markdown(f"""
<div style="margin-bottom:20px;">
    <h1 style="margin-bottom:5px;">📊 NIFTY ΔOI PCR Dashboard</h1>
    <div style="display:flex; align-items:center; gap:15px;">
        <div style="display:flex; align-items:center;">
            <div style="width:12px; height:12px; border-radius:50%; 
                background:{sphere_color}; margin-right:8px; 
                animation: pulse 2s infinite;"></div>
            <span style="font-size:14px; color:{sphere_color}; font-weight:bold;">
                {status_info['status']} • {current_time.strftime('%I:%M:%S %p IST')}
            </span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ================== DATA FETCH ==================
with st.spinner("🔄 Fetching market data..."):
    if 'use_mock' in locals() and use_mock:
        data = get_mock_data(base_strike, dte, manual_range)
        status_msg = "OK"
    else:
        data, status_msg = fetch_pcr(base_strike, dte, manual_range)

if data:
    if data.get("is_mock", False):
        st.info("📡 Using simulated data for demonstration purposes")
    
    st.session_state.last_valid = data
    st.session_state.data_history.append(data)
    
    # Keep only last 50 data points
    if len(st.session_state.data_history) > 50:
        st.session_state.data_history = st.session_state.data_history[-50:]
    
    log(f"PCR={data['pcr']} | Spot={data['spot']:.2f} | PutΔOI={data['put_doi']:,} | CallΔOI={data['call_doi']:,}")
    
    if not data.get("is_mock", False):
        st.success(f"✅ Live data updated at {data['time'].strftime('%H:%M:%S')} IST", icon="✅")
elif st.session_state.last_valid:
    data = st.session_state.last_valid
    st.warning(f"⚠️ Using cached data from {data['time'].strftime('%H:%M:%S')}", icon="⚠️")
    log(f"Data fetch failed: {status_msg}", "WARN")
else:
    st.error(f"Initial data fetch failed: {status_msg}", icon="❌")
    # Provide mock data as fallback
    data = get_mock_data(base_strike, dte, manual_range)
    st.info("📡 Falling back to simulated data")

# ================== PCR SIGNAL DISPLAY ==================
if data:
    signal, message, level, color = pcr_trade_signal(data["pcr"])
    
    st.markdown(f"""
    <div style="margin:20px 0;">
        <div style="background:linear-gradient(135deg, {color}20, {color}10); 
            padding:20px; border-radius:15px; border-left:6px solid {color};">
            <div>
                <h2 style="margin:0; color:{color};">{signal}</h2>
                <p style="margin:5px 0; font-size:16px;">{message}</p>
                <div style="display:flex; align-items:center; gap:20px; margin-top:10px;">
                    <div style="font-size:24px; font-weight:bold;">PCR: {data['pcr']}</div>
                    <div style="font-size:14px; color:#95a5a6;">
                        Range: ±{data.get('strikes', 'N/A')} strikes • DTE: {dte}
                    </div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ================== KEY METRICS ==================
    st.markdown("### 📈 Live Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "SPOT PRICE",
            f"₹{data['spot']:,.2f}",
            delta=None
        )
    
    with col2:
        delta_color = "inverse" if data['put_doi'] > data['call_doi'] else "normal"
        st.metric(
            "PUT ΔOI",
            f"{data['put_doi']:,}",
            delta_color=delta_color
        )
    
    with col3:
        delta_color = "normal" if data['call_doi'] > data['put_doi'] else "inverse"
        st.metric(
            "CALL ΔOI",
            f"{data['call_doi']:,}",
            delta_color=delta_color
        )
    
    with col4:
        delta_color = "normal" if data['pcr'] > 1.25 else "inverse" if data['pcr'] < 0.75 else "off"
        st.metric(
            "PUT/CALL RATIO",
            f"{data['pcr']}",
            delta_color=delta_color
        )

# ================== CHART ==================
if st.session_state.data_history:
    st.markdown("---")
    st.markdown("### 📊 PCR Trend Analysis")
    
    # Create chart
    fig, ax = plt.subplots(figsize=(12, 5))
    
    times = [d["time"] for d in st.session_state.data_history[-30:]]
    pcr_values = [d["pcr"] for d in st.session_state.data_history[-30:]]
    
    ax.plot(times, pcr_values, 'o-', linewidth=2, color=sphere_color, 
           markersize=4, markerfacecolor='white', markeredgewidth=1)
    
    # Add thresholds
    ax.axhline(1.25, color='#2ecc71', linestyle='--', alpha=0.5, label='Bullish (1.25)')
    ax.axhline(1.0, color='white', linestyle='--', alpha=0.3, label='Neutral (1.0)')
    ax.axhline(0.75, color='#e74c3c', linestyle='--', alpha=0.5, label='Bearish (0.75)')
    
    ax.set_title(f'PCR Trend | ATM {base_strike} | {len(times)} data points', 
                fontsize=14, fontweight='bold')
    ax.set_ylabel('PCR Value')
    ax.grid(True, alpha=0.2)
    ax.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig)

# ================== TRADER MINDSET ==================
with st.expander("🧠 Trader Psychology & Mindset", expanded=False):
    tab1, tab2, tab3 = st.tabs(["Mindset", "Risk Management", "Execution"])
    
    with tab1:
        st.markdown("""
        **🎯 Core Principles:**
        - Uncertainty is the only certainty in markets
        - Your self-worth ≠ Your P&L
        - Process > Outcome
        - Patience is a superpower
        """)
    
    with tab2:
        st.markdown("""
        **🛡️ NIFTY-SPECIFIC RULES:**
        - **NO TRADE ON EXPIRY DAYS** - Tuesday is NIFTY 50 weekly expiry
        - **Stop After First Loss** - No revenge trading, preserve capital
        - **No Trades in First 15 Minutes** - Avoid opening volatility (9:15-9:30 IST)
        - Max 2% risk per trade, 5% max daily loss limit
        - PCR > 1.5 = Bullish bias, PCR < 0.8 = Bearish bias
        - Friday positions: Close or hedge before weekend
        """)
    
    with tab3:
        st.markdown("""
        **⚡ Execution Excellence:**
        - Plan your trade, trade your plan
        - Entry is optional, exit is mandatory
        - Discipline > Intelligence
        - Review trades, not just results
        """)

# ================== LOGS ==================
with st.expander("📜 Activity Logs", expanded=False):
    if st.session_state.logs:
        for log_entry in st.session_state.logs[-10:]:
            level_colors = {
                "INFO": "#3498db",
                "WARN": "#f1c40f",
                "ERROR": "#e74c3c"
            }
            
            st.markdown(f"""
            <div style="padding:8px; margin:4px 0; background:#1c1f26; border-radius:5px; 
                 border-left:4px solid {level_colors.get(log_entry['level'], '#95a5a6')};">
                <span style="color:#95a5a6;">{log_entry['time'].strftime('%H:%M:%S IST')}</span>
                <span style="color:{level_colors.get(log_entry['level'], '#95a5a6')}; 
                      font-weight:bold; margin:0 10px;">[{log_entry['level']}]</span>
                <span>{log_entry['message']}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No logs yet. Data will appear here after first fetch.")

# ================== AUTO REFRESH ==================
if auto_refresh and 'refresh_interval' in locals():
    if st.session_state.last_refresh is None:
        st.session_state.last_refresh = get_ist_time()
    else:
        elapsed = (get_ist_time() - st.session_state.last_refresh).seconds
        
        if elapsed >= refresh_interval:
            st.session_state.last_refresh = get_ist_time()
            st.session_state.refresh_count += 1
            time.sleep(0.5)
            st.rerun()
    
    # Countdown timer
    if st.session_state.last_refresh:
        next_refresh = st.session_state.last_refresh + timedelta(seconds=refresh_interval)
        current_time = get_ist_time()
        if next_refresh > current_time:
            time_left = (next_refresh - current_time).seconds
            st.caption(f"⏳ Next auto-refresh in {time_left} seconds")

# ================== FOOTER ==================
st.markdown("---")
st.markdown(f"""
<div style="text-align:center; color:#95a5a6; font-size:12px; padding:20px;">
    <div style="margin-bottom:10px;">
        <span>📊 NIFTY ΔOI PCR Dashboard</span> • 
        <span>⏰ IST: {get_ist_time().strftime('%d %b %Y, %I:%M %p')}</span> • 
        <span>🔐 For Educational Purposes</span>
    </div>
    <div>Data Source: {'Simulated Data' if data.get('is_mock', False) else 'NSE India'} • Based on ΔOI (Change in Open Interest)</div>
</div>
""", unsafe_allow_html=True)
