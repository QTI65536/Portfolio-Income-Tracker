import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import io
import time
import os
import requests

# --- CONFIG & STYLING ---
st.set_page_config(layout="wide", page_title="Income Portfolio Tracker by QTI")

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab"] p { font-size: 28px !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] p { font-size: 24px !important; font-weight: 800 !important; color: #333 !important; }
    [data-testid="stMetricValue"] { font-size: 48px !important; }
    label { font-size: 24px !important; font-weight: bold !important; }
    input { font-size: 22px !important; }
    html, body, [class*="css"] { font-size: 20px; }
    .main { background-color: #fdfdf5; }
    .app-branding { font-size: 22px !important; color: #7f8c8d; font-weight: 400; margin-bottom: -10px; }
    .master-title { 
        font-size: 52px !important; 
        color: #2c3e50; 
        font-weight: 900 !important;
        margin-bottom: 10px !important;
        border-bottom: 3px solid #2ecc71;
        padding-bottom: 10px;
    }
    .stDataFrame, div[data-testid="stTable"] { font-size: 20px !important; }
    </style>
    """, unsafe_allow_html=True)

HARDCODED_CEFS = {'ADX', 'AIO', 'ASGI', 'BME', 'BST', 'BUI', 'CSQ', 'DNP', 'EOS', 'ERH', 'GDV', 'GLU', 'GOF', 'NBXG', 'NIE', 'PCN', 'PDI', 'PDO', 'PDX', 'RFI', 'RLTY', 'RNP', 'RQI', 'STK', 'UTF', 'UTG'}

def clean_numeric(value):
    if pd.isna(value) or value == "": return 0.0
    if isinstance(value, str):
        clean_val = value.replace('$', '').replace(',', '').strip()
        try: return float(clean_val)
        except ValueError: return 0.0
    return float(value)

def strip_ext(filename):
    return filename.rsplit('.', 1)[0] if '.' in filename else filename

# --- OVERHAULED ROBUST DATA ENGINE ---
@st.cache_data(ttl=3600)
def get_stock_data_v4(tickers):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    
    data = {}
    for t in tickers:
        ticker_clean = str(t).strip().upper()
        if not ticker_clean: continue
        try:
            tk = yf.Ticker(ticker_clean, session=session)
            
            # Use fast_info for basic metrics (less likely to be blocked)
            fast = tk.fast_info
            price = fast.get('lastPrice') or fast.get('previousClose') or 0.0
            
            # Standard Info (often blocked on Cloud)
            info = {}
            try:
                info = tk.info
            except:
                pass # Continue with fast_info if full info fails
            
            div_rate = info.get('dividendRate') or 0
            # If info failed, try to estimate dividend from history
            if div_rate == 0:
                hist = tk.dividends
                if not hist.empty:
                    # Sum last 12 months
                    div_rate = hist.last('365D').sum()

            quote_type = info.get('quoteType', 'EQUITY').upper()
            long_summary = info.get('longBusinessSummary', '').lower()
            industry = info.get('industry', '').lower()
            sector_raw = info.get('sector', 'Other')

            is_cef = ticker_clean in HARDCODED_CEFS or "closed-end" in long_summary
            sector = "Closed-End Fund" if is_cef else (quote_type if quote_type == "ETF" else sector_raw)

            # Safety Logic Fallback
            tier = "Tier 2: ⚠️ STABLE"
            if not info:
                tier = "Tier 1: ✅ SAFE" # Default if fundamentals can't be reached
            else:
                ebitda = info.get('ebitda', 1)
                payout = info.get('payoutRatio', 0)
                if payout > 0.85 or ebitda == 0: tier = "Tier 3: 🚨 RISK"

            data[t] = {
                'price': price, 
                'dividendRate': div_rate, 
                'name': info.get('shortName', ticker_clean), 
                'yield': div_rate/price if price > 0 else 0, 
                'sector': sector, 
                'safety_tier': tier, 
                'ex_div': info.get('exDividendDate'), 
                'frequency': 12 if div_rate > 0 and (div_rate/price > 0.08) else 4
            }
            time.sleep(0.2)
        except Exception as e:
            data[t] = {'price': 0, 'dividendRate': 0, 'safety_tier': 'Tier 3: 🚨 RISK', 'sector': 'Unknown', 'yield': 0}
    return data

# --- SESSION STATE & AUTO-LOAD ---
if 'portfolios' not in st.session_state: 
    st.session_state.portfolios = {}
    SAMPLE_FILE = "Sample Portfolio.csv"
    if os.path.exists(SAMPLE_FILE):
        try:
            sample_df = pd.read_csv(SAMPLE_FILE)
            sample_df.columns = sample_df.columns.str.strip()
            sample_df = sample_df[["Ticker", "Shares", "Avg Cost"]].dropna(subset=['Ticker'])
            sample_df['Shares'] = sample_df['Shares'].apply(clean_numeric)
            sample_df['Avg Cost'] = sample_df['Avg Cost'].apply(clean_numeric)
            st.session_state.portfolios[SAMPLE_FILE] = sample_df
            st.session_state.active_portfolio_name = SAMPLE_FILE
        except: pass

if 'active_portfolio_name' not in st.session_state: st.session_state.active_portfolio_name = None

# --- SIDEBAR ---
with st.sidebar:
    st.header("📂 Portfolio Vault")
    uploaded_files = st.file_uploader("Upload CSV Files", type=["csv"], accept_multiple_files=True)
    if uploaded_files:
        for file in uploaded_files:
            if file.name not in st.session_state.portfolios:
                raw_df = pd.read_csv(file)
                raw_df.columns = raw_df.columns.str.strip()
                clean_df = raw_df[["Ticker", "Shares", "Avg Cost"]].dropna(subset=['Ticker']).copy()
                clean_df['Shares'] = clean_df['Shares'].apply(clean_numeric)
                clean_df['Avg Cost'] = clean_df['Avg Cost'].apply(clean_numeric)
                st.session_state.portfolios[file.name] = clean_df
                if st.session_state.active_portfolio_name is None: st.session_state.active_portfolio_name = file.name
    if st.session_state.portfolios:
        for name in list(st.session_state.portfolios.keys()):
            col_sel, col_del = st.columns([4, 1])
            if col_sel.button(f"{'📍 ' if name == st.session_state.active_portfolio_name else ''}{strip_ext(name)}", key=f"sel_{name}", use_container_width=True):
                st.session_state.active_portfolio_name = name
                st.rerun()
            if col_del.button("🗑️", key=f"del_{name}"):
                st.session_state.portfolios.pop(name)
                remaining = list(st.session_state.portfolios.keys())
                st.session_state.active_portfolio_name = remaining[0] if remaining else None
                st.rerun()

st.markdown('<div class="app-branding">Income Portfolio Tracker by QTI</div>', unsafe_allow_html=True)
if not st.session_state.active_portfolio_name:
    st.stop()

active_name = st.session_state.active_portfolio_name
active_display = strip_ext(active_name)
st.markdown(f'<div class="master-title">Portfolio: {active_display}</div>', unsafe_allow_html=True)

tab_dash, tab_edit = st.tabs(["📈 Dashboard & Analytics", "✏️ Edit Positions"])

with tab_edit:
    st.subheader("➕ Add or Update Position")
    with st.form("entry_form", clear_on_submit=True):
        f_col1, f_col2, f_col3 = st.columns(3)
        f_ticker = f_col1.text_input("Ticker Symbol").upper().strip()
        f_shares = f_col2.number_input("Shares", min_value=0.0, step=0.01)
        f_cost = f_col3.number_input("Avg Cost ($)", min_value=0.0, step=0.01)
        if st.form_submit_button("Commit to Portfolio") and f_ticker:
            df = st.session_state.portfolios[active_name]
            if f_ticker in df['Ticker'].values: df.loc[df['Ticker'] == f_ticker, ['Shares', 'Avg Cost']] = [f_shares, f_cost]
            else: st.session_state.portfolios[active_name] = pd.concat([df, pd.DataFrame([{"Ticker": f_ticker, "Shares": f_shares, "Avg Cost": f_cost}])], ignore_index=True)
            st.rerun()
    st.divider()
    curr_df = st.session_state.portfolios[active_name]
    for idx, row in curr_df.iterrows():
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(f"**{row['Ticker']}**")
        c2.write(f"{row['Shares']} Shares")
        c3.write(f"${row['Avg Cost']:.2f} Avg")
        if c4.button("Remove", key=f"rem_{idx}"):
            st.session_state.portfolios[active_name] = curr_df.drop(idx)
            st.rerun()

with tab_dash:
    df = st.session_state.portfolios[active_name].copy()
    if not df.empty:
        with st.spinner('Syncing...'): live_info = get_stock_data_v4(df['Ticker'].str.upper().tolist())
        df['Price'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('price', 0))
        df['Div_Rate'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('dividendRate', 0))
        df['Yield'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('yield', 0))
        df['Safety'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('safety_tier', 'Unknown'))
        df['Sector'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('sector', 'Other'))
        df['Ex_Div'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('ex_div', None))
        df['Frequency'] = df['Ticker'].str.upper().map(lambda x: live_info.get(x, {}).get('frequency', 4))
        df['Market Value'] = df['Shares'] * df['Price']
        df['Annual Income'] = df['Shares'] * df['Div_Rate']
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Account Balance", f"${df['Market Value'].sum():,.0f}")
        m2.metric("Annual Income", f"${df['Annual Income'].sum():,.0f}")
        m3.metric("Div. Yield", f"{(df['Annual Income'].sum()/df['Market Value'].sum()*100) if df['Market Value'].sum() > 0 else 0:.2f}%")
        m4.metric("Yield on Cost", f"{(df['Annual Income'].sum()/(df['Shares']*df['Avg Cost']).sum()*100) if (df['Shares']*df['Avg Cost']).sum() > 0 else 0:.2f}%")
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        h_style = dict(bgcolor="white", font_size=22, font_family="Arial", bordercolor="#2ecc71")
        
        with c1:
            st.subheader("Dynamic Safety Rating")
            def get_saf(group):
                breakdown = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(group['Ticker'], group['Annual Income'])])
                return pd.Series({'Val': group['Annual Income'].sum(), 'Hover': f"<b>Annual Income: ${group['Annual Income'].sum():,.2f}</b><br><br>{breakdown}"})
            saf_sum = df.groupby('Safety').apply(get_saf).reset_index()
            fig = go.Figure(data=[go.Pie(labels=saf_sum['Safety'], values=saf_sum['Val'], hole=0.6, customdata=saf_sum['Hover'], hovertemplate="<br><span style='font-size:24px; font-weight:bold;'>%{label}</span><br><br>%{customdata}<br><extra></extra>")])
            fig.update_layout(height=600, margin=dict(t=80, b=80), hoverlabel=h_style)
            st.plotly_chart(fig, use_container_width=True)
            
        with c2:
            st.subheader("10-Year Income Forecast")
            growth = st.number_input("Est. Growth Rate (%)", value=6.0, step=0.5)
            proj = [df['Annual Income'].sum() * ((1 + growth/100)**i) for i in range(11)]
            fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
            fig_g.update_layout(xaxis_title="Year", yaxis_title="Income ($)", hoverlabel=h_style)
            fig_g.update_traces(hovertemplate="<b>Year: %{x}</b><br>Income: $%{y:,.2f}<extra></extra>")
            st.plotly_chart(fig_g, use_container_width=True)
            
        with c3:
            st.subheader("Sector Analysis")
            view = st.radio("Allocation By:", ["Market Value", "Annual Income"], horizontal=True)
            sec_sum = df.groupby('Sector')[view].sum().reset_index()
            fig_s = go.Figure(data=[go.Pie(labels=sec_sum['Sector'], values=sec_sum[view], hole=0.5, hovertemplate="<br><span style='font-size:24px; font-weight:bold;'>%{label}</span><br><br><b>Amount: $%{value:,.2f}</b><br><extra></extra>")])
            fig_s.update_layout(height=600, margin=dict(t=80, b=80), hoverlabel=h_style)
            st.plotly_chart(fig_s, use_container_width=True)
            
        st.write("---")
        st.subheader("Detailed Analytics")
        st.dataframe(df[['Ticker', 'Sector', 'Safety', 'Price', 'Yield', 'Market Value', 'Annual Income']].sort_values('Market Value', ascending=False).style.format({'Price': '${:,.2f}', 'Yield': '{:.2%}', 'Market Value': '${:,.0f}', 'Annual Income': '${:,.2f}'}), use_container_width=True, hide_index=True)
