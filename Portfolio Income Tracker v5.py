import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os

# --- CONFIG & STYLING ---
st.set_page_config(layout="wide", page_title="Income Portfolio Tracker by QTI")

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab"] p { font-size: 28px !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] p { font-size: 24px !important; font-weight: 800 !important; color: #333 !important; }
    [data-testid="stMetricValue"] { font-size: 48px !important; }
    .app-branding { font-size: 22px !important; color: #7f8c8d; }
    .master-title { font-size: 52px !important; color: #2c3e50; font-weight: 900; border-bottom: 3px solid #2ecc71; }
    </style>
    """, unsafe_allow_html=True)

# --- ARCHITECT'S DATA ENGINE (Version 6.4) ---
@st.cache_data(ttl=3600)
def get_bulk_metadata(tickers):
    if not tickers: return {}, {}
    
    # Rule 2 & 3: Bulk download with auto_adjust to handle Multi-Index and Naming
    raw_data = yf.download(tickers, period="1d", auto_adjust=True, group_by='column')
    
    # Rule 2: Isolate the 'Close' attribute to flatten the Multi-Index
    if len(tickers) > 1:
        prices_df = raw_data['Close']
    else:
        prices_df = raw_data[['Close']]
        prices_df.columns = tickers

    prices = prices_df.iloc[-1].to_dict()
    
    # Fetching Dividends and Metadata
    meta = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            # Use fast_info for cloud stability
            info = tk.info
            div = info.get('dividendRate') or 0
            if div == 0: # Fallback to history if blocked
                h = tk.dividends
                div = h.last('365D').sum() if not h.empty else 0
            
            meta[t] = {
                'price': prices.get(t, 0),
                'div': div,
                'sector': info.get('sector', 'Other'),
                'name': info.get('shortName', t),
                'payout': info.get('payoutRatio', 0)
            }
        except:
            meta[t] = {'price': prices.get(t, 0), 'div': 0, 'sector': 'Other', 'name': t, 'payout': 0}
            
    return meta

def clean_numeric(value):
    try:
        return float(str(value).replace('$', '').replace(',', '').strip())
    except:
        return 0.0

# --- SESSION STATE & AUTO-LOAD ---
if 'portfolios' not in st.session_state:
    st.session_state.portfolios = {}
    SAMPLE = "Sample Portfolio.csv"
    if os.path.exists(SAMPLE):
        try:
            df = pd.read_csv(SAMPLE)
            df.columns = df.columns.str.strip()
            df = df[["Ticker", "Shares", "Avg Cost"]].dropna()
            df['Shares'] = df['Shares'].apply(clean_numeric)
            df['Avg Cost'] = df['Avg Cost'].apply(clean_numeric)
            st.session_state.portfolios[SAMPLE] = df
            st.session_state.active_portfolio_name = SAMPLE
        except: pass

# --- SIDEBAR & NAVIGATION ---
with st.sidebar:
    st.header("📂 Vault")
    up = st.file_uploader("Upload CSV", type="csv", accept_multiple_files=True)
    if up:
        for f in up:
            if f.name not in st.session_state.portfolios:
                d = pd.read_csv(f)
                d.columns = d.columns.str.strip()
                st.session_state.portfolios[f.name] = d[["Ticker", "Shares", "Avg Cost"]].dropna()
                st.session_state.active_portfolio_name = f.name
    
    if st.session_state.portfolios:
        for n in list(st.session_state.portfolios.keys()):
            if st.sidebar.button(f"📍 {n}" if n == st.session_state.active_portfolio_name else n, use_container_width=True):
                st.session_state.active_portfolio_name = n
                st.rerun()

# --- MAIN UI ---
st.markdown('<div class="app-branding">Income Portfolio Tracker by QTI</div>', unsafe_allow_html=True)
active = st.session_state.get('active_portfolio_name')

if not active:
    st.info("Please upload or select a portfolio.")
    st.stop()

st.markdown(f'<div class="master-title">Portfolio: {active.replace(".csv","")}</div>', unsafe_allow_html=True)
t_dash, t_edit = st.tabs(["📊 Dashboard", "✏️ Edit"])

with t_edit:
    df_edit = st.session_state.portfolios[active]
    with st.form("add_ticker"):
        c1, c2, c3 = st.columns(3)
        nt = c1.text_input("Ticker").upper()
        ns = c2.number_input("Shares", min_value=0.0)
        nc = c3.number_input("Avg Cost", min_value=0.0)
        if st.form_submit_button("Add/Update"):
            if nt in df_edit['Ticker'].values:
                df_edit.loc[df_edit['Ticker']==nt, ['Shares','Avg Cost']] = [ns, nc]
            else:
                st.session_state.portfolios[active] = pd.concat([df_edit, pd.DataFrame([{"Ticker":nt, "Shares":ns, "Avg Cost":nc}])])
            st.rerun()
    st.dataframe(df_edit, use_container_width=True)

with t_dash:
    df = st.session_state.portfolios[active].copy()
    if not df.empty:
        tickers = df['Ticker'].unique().tolist()
        with st.spinner("Fetching Cloud Data..."):
            meta = get_bulk_metadata(tickers)
        
        df['Price'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('price', 0))
        df['Div'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('div', 0))
        df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
        df['MV'] = df['Shares'] * df['Price']
        df['Income'] = df['Shares'] * df['Div']
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Balance", f"${df['MV'].sum():,.0f}")
        m2.metric("Income", f"${df['Income'].sum():,.0f}")
        m3.metric("Yield", f"{(df['Income'].sum()/df['MV'].sum()*100) if df['MV'].sum()>0 else 0:.2f}%")
        
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Sector Allocation")
            v = st.radio("By:", ["MV", "Income"], horizontal=True)
            fig = px.pie(df, values=v, names='Sector', hole=0.5)
            # Architect Rule: Use explicit hover formatting
            fig.update_traces(textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Value: $%{value:,.2f}")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("10-Year Income Forecast")
            g = st.number_input("Growth %", value=6.0)
            proj = [df['Income'].sum() * ((1 + g/100)**i) for i in range(11)]
            fig_g = px.area(x=[2024+i for i in range(11)], y=proj)
            fig_g.update_traces(hovertemplate="<b>Year: %{x}</b><br>Income: $%{y:,.2f}")
            st.plotly_chart(fig_g, use_container_width=True)

        st.subheader("Detailed Analytics")
        # Rule 1: Using .format() is safe, avoiding .applymap()
        st.dataframe(df.style.format({
            'Price': '${:,.2f}', 'Div': '${:,.2f}', 
            'MV': '${:,.0f}', 'Income': '${:,.2f}'
        }), use_container_width=True)
