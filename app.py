import streamlit as st
import requests
from datetime import datetime, time as dtime, timedelta
import time
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# ================== PAGE CONFIG ==================
st.set_page_config(
    page_title="NIFTY ΔOI PCR Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ================== GLOBAL CSS (FONT + THEME + ANIMATIONS) ==================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville&display=swap');

html, body, [class*="css"] {
    font-family: 'Libre Baskerville', serif;
}

section[data-testid="stSidebar"] {
    background-color: #121417;
}

/* Pulse animation for live market */
@keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.5; }
    100% { opacity: 1; }
}

@keyframes slideIn {
    from { transform: translateY(-20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.pulse {
    animation: pulse 2s infinite;
}

.slide-in {
    animation: slideIn 0.5s ease-out;
}

.fade-in {
    animation: fadeIn 0.8s ease-in;
}

.status-badge {
    padding: 6px 12px;
    border-radius: 20px;
    font-weight: bold;
    display: inline-block;
    margin-left: 10px;
}

.live-badge {
    background: linear-gradient(90deg, #2ecc71, #27ae60);
    animation: pulse 2s infinite;
}

.after-market-badge {
    background: linear-gradient(90deg, #e74c3c, #c0392b);
}

.refresh-button {
    transition: all 0.3s ease;
    border: 2px solid transparent;
}

.refresh-button:hover {
    transform: scale(1.05);
    border-color: #2ecc71 !important;
}

.metric-card {
    transition: all 0.3s ease;
    border-radius: 10px;
    padding: 15px;
    margin: 5px 0;
}

.metric-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 10px 20px rgba(0,0,0,0.2);
}

.market-open {
    border-left: 5px solid #2ecc71;
    background: linear-gradient(90deg, #1c1f26 0%, rgba(46, 204, 113, 0.05) 100%);
}

.market-closed {
    border-left: 5px solid #e74c3c;
    background: linear-gradient(90deg, #1c1f26 0%, rgba(231, 76, 60, 0.05) 100%);
}

</style>
""", unsafe_allow_html=True)

# ================== UTILITIES ==================
def log(msg, level="INFO"):
    timestamp = datetime.now()
    st.session_state.logs.append({
        "time": timestamp,
        "level": level,
        "message": msg
    })

def market_status():
    now = datetime.now().time()
    today = datetime.now()
    
    # Check if today is Tuesday (weekly expiry day for NIFTY)
    is_tuesday = today.weekday() == 1  # Monday=0, Tuesday=1
    
    # Market hours
    is_market_hours = dtime(9, 20) <= now <= dtime(15, 25)
    
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

def create_sparkline(data_points, height=30):
    """Create HTML sparkline"""
    if len(data_points) < 2:
        return ""
    
    min_val = min(data_points)
    max_val = max(data_points)
    range_val = max_val - min_val if max_val > min_val else 1
    
    points = []
    for i, val in enumerate(data_points):
        x = (i / (len(data_points) - 1)) * 100 if len(data_points) > 1 else 50
        y = ((val - min_val) / range_val) * 100 if range_val > 0 else 50
        points.append(f"{x}% {100 - y}%")
    
    points_str = ", ".join(points)
    
    # Color based on trend
    if len(data_points) >= 2:
        trend = data_points[-1] - data_points[0]
        stroke_color = "#2ecc71" if trend > 0 else "#e74c3c" if trend < 0 else "#f1c40f"
    else:
        stroke_color = "#f1c40f"
    
    return f'''
    <div style="width:100%; height:{height}px; background:#1c1f26; border-radius:5px; padding:5px;">
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline 
                points="{points_str}" 
                fill="none" 
                stroke="{stroke_color}" 
                stroke-width="2"
                stroke-linejoin="round"
                stroke-linecap="round"
                opacity="0.8">
            </polyline>
        </svg>
    </div>
    '''

# ================== NSE SESSION ==================
def create_nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*"
    })
    try:
        s.get("https://www.nseindia.com", timeout=5)
    except:
        pass
    return s

# ================== DATA FETCH ==================
def fetch_pcr(base_strike, dte, manual_range):
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    try:
        r = st.session_state.session.get(url, timeout=10)
        
        if r.status_code != 200:
            return None, f"HTTP Error: {r.status_code}"
        
        data = r.json()
        if "records" not in data:
            return None, "Invalid response format"
        
        records = data["records"]["data"]
        spot = data["records"]["underlyingValue"]
        
        rng = manual_range if manual_range is not None else strike_range_by_dte(dte)
        strikes = [base_strike + i * 50 for i in range(-rng, rng + 1)]
        
        put_doi, call_doi = 0, 0
        
        for row in records:
            if row.get("strikePrice") in strikes:
                if "PE" in row:
                    put_doi += row["PE"].get("changeinOpenInterest", 0)
                if "CE" in row:
                    call_doi += row["CE"].get("changeinOpenInterest", 0)
        
        if call_doi == 0:
            return None, "Zero Call ΔOI"
        
        pcr_value = put_doi / call_doi if call_doi != 0 else 0
        
        return {
            "time": datetime.now(),
            "pcr": round(pcr_value, 2),
            "put_doi": put_doi,
            "call_doi": call_doi,
            "spot": spot,
            "strikes": rng
        }, "OK"
        
    except Exception as e:
        return None, f"Error: {str(e)}"

def pcr_trade_signal(pcr):
    if pcr < 0.75:
        return "PUT", "🔴 Bearish Bias - Put Writing Dominant", "error", "#e74c3c"
    elif 0.75 <= pcr <= 1.25:
        return "NEUTRAL", "⚪ Neutral Zone - Caution Advised", "warning", "#f1c40f"
    else:
        return "CALL", "🟢 Bullish Bias - Strong Put Addition", "success", "#2ecc71"

# ================== SESSION STATE ==================
if "session" not in st.session_state:
    st.session_state.session = create_nse_session()
    st.session_state.logs = []
    st.session_state.data_history = []
    st.session_state.last_valid = None
    st.session_state.last_refresh = None
    st.session_state.refresh_count = 0
    st.session_state.animation_key = 0

# ================== SIDEBAR ==================
with st.sidebar:
    st.title("⚙️ Control Panel")
    
    # Market Status Display - SIMPLIFIED VERSION
    status_info = market_status()
    badge_class = "live-badge" if status_info['status'] == 'LIVE' else "after-market-badge"
    badge_icon = "🟢" if status_info['status'] == 'LIVE' else "🔴"
    
    st.markdown(f"""
    <div class="fade-in metric-card {'market-open' if status_info['status'] == 'LIVE' else 'market-closed'}">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <div>
                <h4 style="margin:0;">Market Status</h4>
            </div>
            <span class="status-badge {badge_class}">
                {badge_icon} {status_info['status']}
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Tuesday (Expiry Day) Warning
    if status_info['is_tuesday']:
        st.warning("⚠️ **TODAY IS EXPIRY DAY** - Exercise Extreme Caution!", icon="⚠️")
    
    st.markdown("---")
    
    # Parameters
    base_strike = st.number_input(
        "🎯 Base Strike Price",
        min_value=10000,
        max_value=50000,
        step=50,
        value=25500,
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
    
    auto_refresh = st.toggle("Auto Refresh", value=True, 
                            help="Automatically refresh data")
    
    if auto_refresh:
        refresh_interval = st.slider(
            "Refresh Interval (seconds)",
            30, 300, 180,
            help="Time between automatic updates"
        )
    
    if st.button("🔄 Refresh Now", type="primary", use_container_width=True):
        st.session_state.refresh_count += 1
        st.session_state.animation_key += 1
        st.rerun()
    
    # Data Stats
    if st.session_state.data_history:
        st.markdown("---")
        st.subheader("📊 Session Stats")
        total_data = len(st.session_state.data_history)
        last_update = st.session_state.data_history[-1]["time"].strftime("%H:%M:%S")
        st.metric("Data Points", total_data)
        st.metric("Last Update", last_update)

# ================== MAIN DASHBOARD ==================
# Header with animated status sphere
status_info = market_status()
current_time = datetime.now().time()
sphere_color = "#2ecc71" if status_info['status'] == 'LIVE' else "#e74c3c"

st.markdown(f"""
<div class="slide-in">
    <h1 style="margin-bottom:10px;">📊 NIFTY ΔOI PCR Dashboard</h1>
    <div style="display:flex; align-items:center; gap:20px; margin-bottom:20px;">
        <div style="display:flex; align-items:center;">
            <div style="width:12px; height:12px; border-radius:50%; 
                background:{sphere_color}; margin-right:8px; 
                animation: pulse 2s infinite;"></div>
            <span style="font-size:14px; color:{sphere_color}; font-weight:bold;">
                {status_info['status']} • {current_time.strftime('%H:%M:%S')}
            </span>
        </div>
        <div style="font-size:14px; color:#95a5a6;">
            Auto-refresh: {'ON' if auto_refresh else 'OFF'}
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ================== DATA FETCH WITH LOADER ==================
with st.spinner("🔄 Fetching live data..."):
    data, status_msg = fetch_pcr(base_strike, dte, manual_range)

if data:
    st.session_state.last_valid = data
    st.session_state.data_history.append(data)
    
    # Keep only last 50 data points for performance
    if len(st.session_state.data_history) > 50:
        st.session_state.data_history = st.session_state.data_history[-50:]
    
    log(f"PCR={data['pcr']} | Spot={data['spot']:.2f} | PutΔOI={data['put_doi']:,} | CallΔOI={data['call_doi']:,}")
    
    # Success animation
    st.success("✅ Data updated successfully!", icon="✅")
    
elif st.session_state.last_valid:
    data = st.session_state.last_valid
    st.warning("⚠️ Using cached data - API fetch failed", icon="⚠️")
    log(f"API fetch failed: {status_msg}", "WARN")
else:
    # Fixed error message without cross marks
    st.error("Initial data fetch failed", icon="❌")
    log(f"Initial fetch failed: {status_msg}", "ERROR")

# ================== PCR SIGNAL DISPLAY ==================
if data:
    signal, message, level, color = pcr_trade_signal(data["pcr"])
    
    # Create sparkline for PCR trend
    pcr_history = [d["pcr"] for d in st.session_state.data_history[-10:]]
    sparkline_html = create_sparkline(pcr_history)
    
    st.markdown(f"""
    <div class="fade-in" style="margin:20px 0;">
        <div style="background:linear-gradient(135deg, {color}20, {color}10); 
            padding:20px; border-radius:15px; border-left:6px solid {color};
            transition: all 0.3s ease;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
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
                <div style="width:150px; height:60px;">
                    {sparkline_html}
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ================== KEY METRICS WITH CARDS ==================
    st.markdown("### 📈 Live Metrics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card fade-in" style="border-top:4px solid #2ecc71;">
            <div style="font-size:12px; color:#95a5a6;">SPOT PRICE</div>
            <div style="font-size:24px; font-weight:bold; color:#2ecc71;">₹{data['spot']:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        delta_color = "#2ecc71" if data['put_doi'] > data['call_doi'] else "#e74c3c"
        st.markdown(f"""
        <div class="metric-card fade-in" style="border-top:4px solid {delta_color};">
            <div style="font-size:12px; color:#95a5a6;">PUT ΔOI</div>
            <div style="font-size:24px; font-weight:bold; color:{delta_color};">{data['put_doi']:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        delta_color = "#e74c3c" if data['call_doi'] > data['put_doi'] else "#2ecc71"
        st.markdown(f"""
        <div class="metric-card fade-in" style="border-top:4px solid {delta_color};">
            <div style="font-size:12px; color:#95a5a6;">CALL ΔOI</div>
            <div style="font-size:24px; font-weight:bold; color:{delta_color};">{data['call_doi']:,}</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        ratio_color = color
        st.markdown(f"""
        <div class="metric-card fade-in" style="border-top:4px solid {ratio_color};">
            <div style="font-size:12px; color:#95a5a6;">PUT/CALL RATIO</div>
            <div style="font-size:24px; font-weight:bold; color:{ratio_color};">{data['pcr']}</div>
        </div>
        """, unsafe_allow_html=True)

# ================== AFTER-MARKET ENHANCEMENTS ==================
if status_info["status"] == "AFTER_MARKET":
    st.markdown("---")
    
    with st.container():
        st.markdown("### 🌙 After-Market Analysis")
        
        if st.session_state.data_history:
            # Create day summary
            day_data = st.session_state.data_history
            pcr_values = [d["pcr"] for d in day_data]
            spot_values = [d["spot"] for d in day_data]
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                avg_pcr = np.mean(pcr_values) if pcr_values else 0
                st.metric("📊 Average PCR", f"{avg_pcr:.2f}")
            
            with col2:
                max_pcr = max(pcr_values) if pcr_values else 0
                st.metric("📈 Max PCR", f"{max_pcr:.2f}")
            
            with col3:
                min_pcr = min(pcr_values) if pcr_values else 0
                st.metric("📉 Min PCR", f"{min_pcr:.2f}")
            
            # Summary chart
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
            
            # PCR Chart
            times = [d["time"] for d in day_data]
            ax1.plot(times, pcr_values, 'o-', linewidth=2, color='#e74c3c', alpha=0.7)
            ax1.fill_between(times, 0.75, 1.25, alpha=0.1, color='yellow')
            ax1.axhline(1.0, linestyle='--', color='white', alpha=0.5)
            ax1.set_title('Daily PCR Trend (After-Market)', fontsize=14, fontweight='bold')
            ax1.set_ylabel('PCR Value')
            ax1.grid(True, alpha=0.3)
            
            # Spot Price Chart
            ax2.plot(times, spot_values, 'o-', linewidth=2, color='#2ecc71', alpha=0.7)
            ax2.set_title('NIFTY Spot Price', fontsize=14, fontweight='bold')
            ax2.set_ylabel('Price (₹)')
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            st.pyplot(fig)
            
            # Export option
            if st.button("📥 Export Today's Data", use_container_width=True):
                df = pd.DataFrame(st.session_state.data_history)
                csv = df.to_csv(index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv,
                    file_name=f"nifty_pcr_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )

# ================== INTERACTIVE CHART ==================
if st.session_state.data_history:
    st.markdown("---")
    st.markdown("### 📊 PCR Trend Analysis")
    
    # Chart controls
    chart_col1, chart_col2 = st.columns([3, 1])
    
    with chart_col2:
        chart_type = st.selectbox(
            "Chart Type",
            ["Line", "Area", "Scatter"],
            index=0
        )
        show_avg = st.toggle("Show Moving Average", value=True)
        show_thresholds = st.toggle("Show Thresholds", value=True)
    
    with chart_col1:
        fig, ax = plt.subplots(figsize=(12, 5))
        
        times = [d["time"] for d in st.session_state.data_history]
        pcr_values = [d["pcr"] for d in st.session_state.data_history]
        
        if chart_type == "Line":
            ax.plot(times, pcr_values, 'o-', linewidth=2, color=sphere_color, 
                   markersize=4, markerfacecolor='white', markeredgewidth=1)
        elif chart_type == "Area":
            ax.fill_between(times, pcr_values, alpha=0.3, color=sphere_color)
            ax.plot(times, pcr_values, color=sphere_color, linewidth=2)
        else:
            ax.scatter(times, pcr_values, color=sphere_color, s=50, alpha=0.6)
        
        if show_avg and len(pcr_values) > 5:
            window = min(5, len(pcr_values))
            moving_avg = pd.Series(pcr_values).rolling(window=window).mean()
            ax.plot(times, moving_avg, '--', color='#f1c40f', linewidth=2, 
                   label=f'{window}-period MA')
        
        if show_thresholds:
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

# ================== TRADER MINDSET WITH ACCORDION ==================
with st.expander("🧠 Trader Psychology & Mindset", expanded=False):
    tab1, tab2, tab3 = st.tabs(["Mindset", "Risk Management", "Execution"])
    
    with tab1:
        st.markdown("""
        <div style="background:#1c1f26; padding:15px; border-radius:10px; border-left:4px solid #2ecc71;">
        <h4>🎯 Core Principles:</h4>
        <ul>
        <li>Uncertainty is the only certainty in markets</li>
        <li>Your self-worth ≠ Your P&L</li>
        <li>Process > Outcome</li>
        <li>Patience is a superpower</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)
    
    with tab2:
        # UPDATED RISK MANAGEMENT RULES
        st.markdown("""
        <div style="background:#1c1f26; padding:15px; border-radius:10px; border-left:4px solid #e74c3c;">
        <h4>🛡️ Risk Rules:</h4>
        <ul>
        <li><strong>NO TRADE ON EXPIRY DAYS</strong> - Tuesday is NIFTY 50 weekly expiry</li>
        <li><strong>Stop Trading After First Loss</strong> - Prevents revenge trading</li>
        <li><strong>Avoid First 15 Minutes</strong> - No trades during market opening volatility</li>
        <li>Use stop losses religiously</li>
        <li>Position size based on conviction, not hope</li>
        <li>Cut losses quickly, let winners run</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)
    
    with tab3:
        st.markdown("""
        <div style="background:#1c1f26; padding:15px; border-radius:10px; border-left:4px solid #f1c40f;">
        <h4>⚡ Execution Excellence:</h4>
        <ul>
        <li>Plan your trade, trade your plan</li>
        <li>Entry is optional, exit is mandatory</li>
        <li>Discipline > Intelligence</li>
        <li>Review trades, not just results</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)

# ================== LOGS WITH FILTERS ==================
with st.expander("📜 Activity Logs", expanded=False):
    if st.session_state.logs:
        # Filter options
        col1, col2 = st.columns(2)
        with col1:
            show_levels = st.multiselect(
                "Filter by level:",
                ["INFO", "WARN", "ERROR"],
                default=["INFO", "WARN", "ERROR"]
            )
        with col2:
            if st.button("Clear Logs"):
                st.session_state.logs = []
                st.rerun()
        
        # Display filtered logs
        filtered_logs = [log for log in st.session_state.logs if log["level"] in show_levels]
        
        for log_entry in filtered_logs[-20:]:
            level_colors = {
                "INFO": "#3498db",
                "WARN": "#f1c40f",
                "ERROR": "#e74c3c"
            }
            
            st.markdown(f"""
            <div style="padding:8px; margin:4px 0; background:#1c1f26; 
                 border-radius:5px; border-left:4px solid {level_colors.get(log_entry['level'], '#95a5a6')};">
                <span style="color:#95a5a6;">{log_entry['time'].strftime('%H:%M:%S')}</span>
                <span style="color:{level_colors.get(log_entry['level'], '#95a5a6')}; 
                      font-weight:bold; margin:0 10px;">[{log_entry['level']}]</span>
                <span>{log_entry['message']}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No logs yet. Data will appear here after first fetch.")

# ================== AUTO REFRESH LOGIC ==================
if auto_refresh and 'refresh_interval' in locals():
    if st.session_state.last_refresh is None:
        st.session_state.last_refresh = datetime.now()
    else:
        elapsed = (datetime.now() - st.session_state.last_refresh).seconds
        
        if elapsed >= refresh_interval:
            st.session_state.last_refresh = datetime.now()
            st.session_state.refresh_count += 1
            st.session_state.animation_key += 1
            
            # Show refresh animation
            refresh_placeholder = st.empty()
            with refresh_placeholder:
                st.markdown(f"""
                <div class="fade-in" style="text-align:center; padding:10px; background:#1c1f26; border-radius:10px;">
                    🔄 Auto-refreshing data... (Refresh #{st.session_state.refresh_count})
                </div>
                """, unsafe_allow_html=True)
                time.sleep(0.5)
            
            st.rerun()
    
    # Countdown timer
    if st.session_state.last_refresh:
        next_refresh = st.session_state.last_refresh + timedelta(seconds=refresh_interval)
        time_left = (next_refresh - datetime.now()).seconds
        st.caption(f"⏳ Next auto-refresh in {time_left} seconds")

# ================== FOOTER ==================
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:#95a5a6; font-size:12px; padding:20px;">
    <div style="display:flex; justify-content:center; gap:30px; margin-bottom:10px;">
        <span>📊 NIFTY ΔOI PCR Dashboard</span>
        <span>⚡ Real-time PCR Analytics</span>
        <span>🔐 For Educational Purposes</span>
    </div>
    <div>Data Source: NSE India • Update Frequency: {refresh_interval if auto_refresh else 'Manual'} seconds</div>
</div>
""", unsafe_allow_html=True)

# python -m streamlit run app.py
