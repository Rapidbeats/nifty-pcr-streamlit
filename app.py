import streamlit as st
import requests
from datetime import datetime, time as dtime
import time
import matplotlib.pyplot as plt

# ================== PAGE CONFIG ==================
st.set_page_config(
    page_title="NIFTY ΔOI PCR Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ================== GLOBAL CSS (FONT + THEME) ==================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville&display=swap');

html, body, [class*="css"] {
    font-family: 'Libre Baskerville', serif;
}

section[data-testid="stSidebar"] {
    background-color: #121417;
}

</style>
""", unsafe_allow_html=True)

# ================== UTILITIES ==================
def log(msg, level="INFO"):
    st.session_state.logs.append(
        f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}"
    )

def market_status():
    now = datetime.now().time()
    return "LIVE" if dtime(9, 20) <= now <= dtime(15, 25) else "AFTER_MARKET"

def strike_range_by_dte(dte):
    if dte >= 7:
        return 7
    if 4 <= dte <= 6:
        return 5
    if 2 <= dte <= 3:
        return 3
    return 1

# ================== NSE SESSION ==================
def create_nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "application/json, text/plain, */*"
    })
    s.get("https://www.nseindia.com", timeout=5)
    return s

# ================== DATA FETCH ==================
def fetch_pcr(base_strike, dte, manual_range):
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    try:
        r = st.session_state.session.get(url, timeout=10)

        if r.status_code != 200:
            return None, f"HTTP_ERROR: {r.status_code}"

        if "application/json" not in r.headers.get("Content-Type", ""):
            return None, "NON_JSON_RESPONSE"

        data = r.json()
        if "records" not in data:
            return None, "NO_RECORDS_KEY"

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
            return None, "ZERO_CALL_DOI"

        return {
            "time": datetime.now(),
            "pcr": round(put_doi / call_doi, 2) if call_doi != 0 else 0,
            "put_doi": put_doi,
            "call_doi": call_doi,
            "spot": spot
        }, "OK"

    except Exception as e:
        return None, f"EXCEPTION: {str(e)}"

def pcr_trade_signal(pcr):
    if pcr < 0.75:
        return "PUT", "🔴 Bearish ΔOI — Put Writing Weak", "error"
    elif 0.75 <= pcr <= 1.25:
        return "NO TRADE", "⚪ Neutral Zone — Avoid Trades", "warning"
    else:
        return "CALL", "🟢 Bullish ΔOI — Strong Put Addition", "success"

# ================== SESSION STATE ==================
if "session" not in st.session_state:
    st.session_state.session = create_nse_session()
    st.session_state.logs = []
    st.session_state.times = []
    st.session_state.pcrs = []
    st.session_state.last_valid = None
    st.session_state.last_refresh = None
    st.session_state.refresh_counter = 0

# ================== SIDEBAR ==================
st.sidebar.title("⚙️ Controls")

base_strike = st.sidebar.number_input(
    "ATM / Base Strike",
    step=50,
    value=22500
)

dte = st.sidebar.slider("Days to Expiry (DTE)", 0, 10, 3)

manual_range = st.sidebar.selectbox(
    "± Strike Range",
    [None, 1, 2, 3, 4, 5, 7],
    index=0
)

refresh = st.sidebar.slider(
    "Refresh (seconds)",
    60, 300, 180
)

# Add auto-refresh checkbox
auto_refresh = st.sidebar.checkbox("🔄 Enable Auto Refresh", value=True)

# Manual refresh button
if st.sidebar.button("🔄 Refresh Now"):
    st.session_state.refresh_counter += 1
    st.rerun()

# ================== HEADER ==================
status = market_status()
st.title("📊 NIFTY ΔOI PCR Dashboard")
st.markdown(f"**Market Mode:** 🟢 `{status}`")

# ================== DATA UPDATE ==================
data, status_msg = fetch_pcr(base_strike, dte, manual_range)

if data:
    st.session_state.last_valid = data
    st.session_state.times.append(data["time"])
    st.session_state.pcrs.append(data["pcr"])
    log(f"PCR={data['pcr']} | Spot={round(data['spot'], 2)} | PutΔOI={data['put_doi']:,} | CallΔOI={data['call_doi']:,}")
elif st.session_state.last_valid:
    data = st.session_state.last_valid
    log(f"Fetch failed → {status_msg}, using cached data", "WARN")
else:
    st.error(f"Initial fetch failed: {status_msg}")
    log(f"Initial fetch failed → {status_msg}", "ERROR")

# ================== DISPLAY DATA ==================
if data:
    signal, message, level = pcr_trade_signal(data["pcr"])
    
    # Display signal with colored box
    color_map = {
        "success": "#2ecc71",  # Green
        "warning": "#f1c40f",  # Yellow
        "error": "#e74c3c"     # Red
    }
    
    border_color = color_map.get(level, "#3498db")
    
    st.markdown(
        f"""
        <div style="
            padding:12px;
            border-radius:10px;
            background:#1c1f26;
            border-left:6px solid {border_color};
            margin-bottom:15px;
            font-size:16px;">
            <b>PCR ΔOI Bias:</b> {signal} | <b>Value:</b> {data['pcr']}<br>
            <small>{message}</small>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Display key metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Spot Price", f"₹{data['spot']:,.2f}")
    with col2:
        st.metric("Put ΔOI", f"{data['put_doi']:,}")
    with col3:
        st.metric("Call ΔOI", f"{data['call_doi']:,}")
    with col4:
        delta_color = "normal"
        if data["pcr"] > 1.25:
            delta_color = "inverse"
        elif data["pcr"] < 0.75:
            delta_color = "normal"
        st.metric("Put/Call Ratio", f"{data['pcr']}", delta_color=delta_color)

# ================== TRADER MINDSET ==================
with st.expander("🧠 Trader Mindset — Execution > P&L", expanded=False):
    st.markdown("""
- **Uncertainty is normal** — no trade outcome is predictable  
- **Risk is always present** — discipline protects capital  
- **Self-worth is not tied to P&L**  
- **Execution quality matters more than results**  
- **Let winners run without fear**
    """)

# ================== CHART ==================
if data and len(st.session_state.times) > 1:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(st.session_state.times, st.session_state.pcrs, marker="o", linewidth=2, markersize=4)
    ax.axhline(1.0, linestyle="--", color="white", alpha=0.5, label="Neutral (1.0)")
    ax.axhline(1.25, linestyle="--", color="green", alpha=0.5, label="Bullish (1.25)")
    ax.axhline(0.75, linestyle="--", color="red", alpha=0.5, label="Bearish (0.75)")
    
    # Fill between thresholds
    ax.fill_between(st.session_state.times, 0.75, 1.25, alpha=0.1, color="yellow")
    ax.fill_between(st.session_state.times, 1.25, max(st.session_state.pcrs + [1.5]), alpha=0.1, color="green")
    ax.fill_between(st.session_state.times, min(st.session_state.pcrs + [0.5]), 0.75, alpha=0.1, color="red")
    
    ax.set_title(
        f"ΔOI PCR | ATM {base_strike} | DTE {dte} | Range ±{manual_range if manual_range else strike_range_by_dte(dte)}"
    )
    ax.set_xlabel("Time")
    ax.set_ylabel("PCR Value")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig)
elif data:
    st.info("Collecting more data points for chart...")

# ================== LOGS ==================
with st.expander("📜 Logs"):
    for l in st.session_state.logs[-15:]:
        st.text(l)
    if not st.session_state.logs:
        st.text("No logs yet...")

# ================== AUTO REFRESH (USING STREAMLIT BUILT-IN) ==================
if auto_refresh:
    # Show refresh count and next refresh time
    current_time = datetime.now()
    if st.session_state.last_refresh:
        time_since_last = (current_time - st.session_state.last_refresh).seconds
        time_to_next = max(0, refresh - time_since_last)
        st.sidebar.markdown(f"**Next refresh in:** {time_to_next}s")
    
    # Auto-refresh logic
    if st.session_state.last_refresh is None:
        st.session_state.last_refresh = current_time
    else:
        time_since_last = (current_time - st.session_state.last_refresh).seconds
        if time_since_last >= refresh:
            st.session_state.last_refresh = current_time
            st.session_state.refresh_counter += 1
            st.rerun()
    
    # Display refresh counter
    st.sidebar.markdown(f"**Refresh count:** {st.session_state.refresh_counter}")
else:
    st.sidebar.info("Auto-refresh disabled")
