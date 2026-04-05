import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

# --- CONFIG & STYLING ---
st.set_page_config(layout="wide", page_title="Income Portfolio Tracker by QTI")

st.markdown("""
    <style>
    .stTabs [data-baseweb="tab"] p { font-size: 28px !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] p { font-size: 24px !important; font-weight: 800 !important; color: #333 !important; }
    [data-testid="stMetricValue"] { font-size: 48px !important; }
    .master-title { font-size: 52px !important; color: #2c3e50; font-weight: 900; border-bottom: 3px solid #2ecc71; padding-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

HOVER_STYLE = dict(bgcolor="white", font_size=20, font_family="Arial", bordercolor="#2ecc71")

# --- DATA ENGINE (WITH DIVIDEND RECOVERY) ---
@st.cache_data(ttl=3600)
def get_cloud_data(tickers):
    if not tickers: return {}
    # Bulk Download for Price
    raw_data = yf.download(tickers, period="5d", auto_adjust=True, progress=False)
    if len(tickers) > 1: prices_df = raw_data['Close']
    else:
        prices_df = raw_data[['Close']]
        prices_df.columns = tickers
    prices = prices_df.iloc[-1].to_dict()
    
    meta = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            
            # --- TRIPLE-CHECK DIVIDEND RECOVERY ---
            div = float(info.get('dividendRate') or 0)
            history = tk.dividends
            
            # If rate is 0 (common for DIVO/JEPI), sum the last 12 months of history
            if div == 0 and not history.empty:
                one_year_ago = datetime.now() - timedelta(days=365)
                last_year_divs = history[history.index > one_year_ago]
                div = float(last_year_divs.sum())
            
            # Calculate Frequency based on actual payment counts
            if not history.empty:
                recent_history = history[history.index > (datetime.now() - timedelta(days=365))]
                pay_count = len(recent_history)
                freq = 12 if pay_count > 6 else 4
            else:
                freq = 4

            # --- SECTOR & SAFETY LOGIC ---
            sector = info.get('sector', info.get('quoteType', 'Other'))
            if t in ['DIVO', 'JEPI', 'JEPQ', 'SCHD', 'VYM']: sector = "Income ETF"
            
            red_flags = []
            if sector not in ["ETF", "Income ETF", "Closed-End Fund"]:
                payout = info.get('payoutRatio', 0) or 0
                if payout > 0.80: red_flags.append("High Payout")
                if (info.get('debtToEquity', 0) or 0) > 250: red_flags.append("High Leverage")

            tier = "Tier 1: ✅ SAFE" if len(red_flags) == 0 else ("Tier 2: ⚠️ STABLE" if len(red_flags) == 1 else "Tier 3: 🚨 RISK")

            meta[t] = {
                'price': float(prices.get(t, 0)), 'div': div, 'sector': sector,
                'safety': tier, 'freq': freq, 'ex_date': info.get('exDividendDate'),
                'name': info.get('shortName', t)
            }
        except Exception as e:
            meta[t] = {'price': float(prices.get(t, 0)), 'div': 0.0, 'sector': 'Other', 'safety': 'Tier 3: 🚨 RISK', 'freq': 4, 'ex_date': None, 'name': t}
    return meta

def clean_numeric(value):
    try:
        s = str(value).replace('$', '').replace(',', '').strip()
        return float(s) if s != "" else 0.0
    except: return 0.0

# --- MAIN APP ---
if 'portfolios' not in st.session_state:
    st.session_state.portfolios = {}

with st.sidebar:
    st.header("📂 Portfolio Vault")
    up = st.file_uploader("Upload CSV", type="csv", accept_multiple_files=True)
    if up:
        for f in up:
            if f.name not in st.session_state.portfolios:
                d = pd.read_csv(f); d.columns = d.columns.str.strip()
                st.session_state.portfolios[f.name] = d[["Ticker", "Shares", "Avg Cost"]].dropna()
                st.session_state.active_portfolio_name = f.name
    
    if st.session_state.portfolios:
        for n in list(st.session_state.portfolios.keys()):
            if st.sidebar.button(n, use_container_width=True):
                st.session_state.active_portfolio_name = n
                st.rerun()

active = st.session_state.get('active_portfolio_name')
if not active: st.stop()

st.markdown(f'<div class="master-title">{active.replace(".csv","")} Overview</div>', unsafe_allow_html=True)
t_dash, t_edit = st.tabs(["📊 Dashboard", "✏️ Edit Positions"])

with t_dash:
    df = st.session_state.portfolios[active].copy()
    df['Shares'] = df['Shares'].apply(clean_numeric)
    
    with st.spinner("Calculating Yields & Safety..."):
        meta = get_cloud_data(df['Ticker'].unique().tolist())
    
    df['Price'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('price', 0))
    df['Div'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('div', 0))
    df['Market Value'] = df['Shares'] * df['Price']
    df['Annual Income'] = df['Shares'] * df['Div']
    df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
    df['Safety'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('safety', 'Tier 3: 🚨 RISK'))
    df['Freq'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('freq', 4))
    df['Ex_Date'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('ex_date'))

    m1, m2, m3 = st.columns(3)
    m1.metric("Account Balance", f"${df['Market Value'].sum():,.0f}")
    m2.metric("Annual Income", f"${df['Annual Income'].sum():,.2f}")
    m3.metric("Dividend Yield", f"{(df['Annual Income'].sum()/df['Market Value'].sum()*100) if df['Market Value'].sum()>0 else 0:.2f}%")

    st.divider()
    c1, c2, c3 = st.columns(3)
    
    def draw_pie(pdf, val_col, label_col, hole=0.5):
        def agg(g):
            s_g = g.sort_values(val_col, ascending=False).head(15)
            b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g[val_col])])
            return pd.Series({'Val': g[val_col].sum(), 'Hover': f"<b>Total: ${g[val_col].sum():,.2f}</b><br><br>{b}"})
        sum_df = pdf.groupby(label_col).apply(agg).reset_index()
        f = go.Figure(data=[go.Pie(labels=sum_df[label_col], values=sum_df['Val'], hole=hole, customdata=sum_df['Hover'], hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>")])
        f.update_layout(height=600, margin=dict(t=30, b=80), hoverlabel=HOVER_STYLE)
        st.plotly_chart(f, use_container_width=True)

    with c1:
        st.subheader("Safety Rating")
        draw_pie(df, "Annual Income", "Safety", hole=0.6)
    with c2:
        st.subheader("10-Year Income Forecast")
        g = st.number_input("Growth %", value=6.0)
        proj = [df['Annual Income'].sum() * ((1 + g/100)**i) for i in range(11)]
        fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
        fig_g.update_layout(hoverlabel=HOVER_STYLE, height=450)
        st.plotly_chart(fig_g, use_container_width=True)
    with c3:
        st.subheader("Sector Allocation")
        draw_pie(df, "Market Value", "Sector")

    # CALENDAR
    st.divider()
    st.subheader("📅 Monthly Income Distribution")
    cal_list = []
    mnths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for _, r in df.iterrows():
        if r['Annual Income'] > 0:
            f, ex = int(r['Freq']), r['Ex_Date']
            start = datetime.fromtimestamp(ex).month if ex else (1 if f==12 else 3)
            for i in range(f):
                idx = (start + (i * (12//f)) - 1) % 12
                cal_list.append({'Ticker': r['Ticker'], 'Month': mnths[idx], 'Income': r['Annual Income']/f, 'Sort': idx})
    
    if cal_list:
        c_df = pd.DataFrame(cal_list)
        c_sum = c_df.groupby(['Month', 'Sort'])['Income'].sum().reset_index().sort_values('Sort')
        fig_c = px.bar(c_sum, x='Month', y='Income', text_auto='.2s')
        fig_c.update_layout(hoverlabel=HOVER_STYLE, height=500)
        st.plotly_chart(fig_c, use_container_width=True)

    st.subheader("Detailed Analytics")
    st.dataframe(df[['Ticker', 'Sector', 'Safety', 'Price', 'Market Value', 'Annual Income']].sort_values('Market Value', ascending=False).style.format({
        'Price': '${:,.2f}', 'Market Value': '${:,.0f}', 'Annual Income': '${:,.2f}'
    }), use_container_width=True, hide_index=True)
