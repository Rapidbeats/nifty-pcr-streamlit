import streamlit as st
import requests
from datetime import datetime, time as dtime
from streamlit_extras.app_autorefresh import st_autorefresh
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
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })
    s.get("https://www.nseindia.com", timeout=5)
    return s

# ================== DATA FETCH ==================
def fetch_pcr(base_strike, dte, manual_range):
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    try:
        r = st.session_state.session.get(url, timeout=10)

        if r.status_code != 200:
            return None, "HTTP_ERROR"

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
                put_doi += row.get("PE", {}).get("changeinOpenInterest", 0)
                call_doi += row.get("CE", {}).get("changeinOpenInterest", 0)

        if call_doi == 0:
            return None, "ZERO_CALL_DOI"

        return {
            "time": datetime.now(),
            "pcr": round(put_doi / call_doi, 2),
            "put_doi": put_doi,
            "call_doi": call_doi,
            "spot": spot
        }, "OK"

    except Exception as e:
        return None, str(e)

def pcr_trade_signal(pcr):
    if pcr < 0.75:
        return "PUT", "🔴 Bearish ΔOI — Put Writing Weak", "error"
    elif 0.75 <= pcr <= 1.25:
        return "NO TRADE", "⚪ Neutral Zone — Avoid Trades", "warning"
    else:
        return "CALL", "🟢 Bullish ΔOI — Strong Put Addition", "success"
if data:
    signal, message, level = pcr_trade_signal(data["pcr"])

    if level == "success":
        st.success(f"📈 TRADE SIGNAL: {signal} | PCR = {data['pcr']}")

    elif level == "warning":
        st.warning(f"⛔ NO TRADE ZONE | PCR = {data['pcr']}")

    else:
        st.error(f"📉 TRADE SIGNAL: {signal} | PCR = {data['pcr']}")

# ================== SESSION STATE ==================
if "session" not in st.session_state:
    st.session_state.session = create_nse_session()
    st.session_state.logs = []
    st.session_state.times = []
    st.session_state.pcrs = []
    st.session_state.last_valid = None

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

# ================== HEADER ==================
status = market_status()
st.title("📊 NIFTY ΔOI PCR Dashboard")
st.markdown(f"**Market Mode:** 🟢 `{status}`")
if data:
    st.markdown(
        f"""
        <div style="
            padding:12px;
            border-radius:10px;
            background:#1c1f26;
            border-left:6px solid {'#2ecc71' if data['pcr']>1.25 else '#e74c3c' if data['pcr']<0.75 else '#f1c40f'};
            margin-bottom:15px;
            font-size:16px;">
            <b>PCR ΔOI Bias:</b> {signal} | <b>Value:</b> {data['pcr']}
        </div>
        """,
        unsafe_allow_html=True
    )
# ================== TRADER MINDSET ==================
with st.expander("🧠 Trader Mindset — Execution > P&L", expanded=False):
    st.markdown("""
- **Uncertainty is normal** — no trade outcome is predictable  
- **Risk is always present** — discipline protects capital  
- **Self-worth is not tied to P&L**  
- **Execution quality matters more than results**  
- **Let winners run without fear**
    """)

# ================== DATA UPDATE ==================
data, status_msg = fetch_pcr(base_strike, dte, manual_range)

if data:
    st.session_state.last_valid = data
    st.session_state.times.append(data["time"])
    st.session_state.pcrs.append(data["pcr"])
    log(f"PCR={data['pcr']} | Spot={round(data['spot'], 2)}")

elif st.session_state.last_valid:
    data = st.session_state.last_valid
    log("Using cached data", "WARN")

else:
    log(f"Fetch failed → {status_msg}", "ERROR")

# ================== CHART ==================
if data:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(st.session_state.times, st.session_state.pcrs, marker="o")
    ax.axhline(1.0, linestyle="--", label="Neutral")
    ax.axhline(1.3, linestyle="--", label="Bullish Crowd")
    ax.axhline(0.7, linestyle="--", label="Bearish Crowd")

    ax.set_title(
        f"ΔOI PCR | ATM {base_strike} | PutΔOI {data['put_doi']} | CallΔOI {data['call_doi']}"
    )
    ax.legend()
    st.pyplot(fig)

# ================== LOGS ==================
with st.expander("📜 Logs"):
    for l in st.session_state.logs[-15:]:
        st.text(l)

# ================== AUTO REFRESH (SAFE) ==================
st_autorefresh(
    interval=refresh * 1000,
    key="pcr_refresh"
)
