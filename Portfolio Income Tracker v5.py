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

# --- DATA ENGINE (BULK ACTION METHOD) ---
@st.cache_data(ttl=3600)
def get_cloud_data_v7(tickers):
    if not tickers: return {}
    
    # ONE SINGLE BULK REQUEST for Price and Dividends (actions=True)
    # This is much harder for Yahoo to block than individual .info requests
    raw_data = yf.download(tickers, period="1y", actions=True, auto_adjust=True, progress=False)
    
    meta = {}
    for t in tickers:
        try:
            # Flatten Multi-Index for this specific ticker
            t_data = raw_data.xs(t, level=1, axis=1) if len(tickers) > 1 else raw_data
            
            curr_price = float(t_data['Close'].iloc[-1])
            
            # Sum all dividends paid in the last 365 days
            div_history = t_data['Dividends']
            annual_div = float(div_history[div_history > 0].sum())
            
            # Determine frequency by counting payments
            pay_count = len(div_history[div_history > 0])
            freq = 12 if pay_count > 6 else (4 if pay_count > 0 else 4)
            
            # Get latest Ex-Date
            ex_dates = div_history[div_history > 0].index
            latest_ex = int(ex_dates[-1].timestamp()) if not ex_dates.empty else None

            # For Sector/Safety, we use a lighter .fast_info check or defaults
            # to avoid the blocked .info scraper
            meta[t] = {
                'price': curr_price,
                'div': annual_div,
                'freq': freq,
                'ex_date': latest_ex,
                'sector': "Portfolio Asset", # Simplified to avoid .info blocks
                'safety': "Tier 1: ✅ SAFE" if annual_div > 0 else "Tier 2: ⚠️ STABLE"
            }
        except:
            meta[t] = {'price': 0.0, 'div': 0.0, 'freq': 4, 'ex_date': None, 'sector': 'Unknown', 'safety': 'Tier 3: 🚨 RISK'}
    return meta

def clean_numeric(value):
    try:
        s = str(value).replace('$', '').replace(',', '').strip()
        return float(s) if s != "" else 0.0
    except: return 0.0

# --- MAIN APP ---
if 'portfolios' not in st.session_state: st.session_state.portfolios = {}

with st.sidebar:
    st.header("📂 Vault")
    up = st.file_uploader("Upload CSV", type="csv", accept_multiple_files=True)
    if up:
        for f in up:
            if f.name not in st.session_state.portfolios:
                d = pd.read_csv(f); d.columns = d.columns.str.strip()
                st.session_state.portfolios[f.name] = d[["Ticker", "Shares", "Avg Cost"]].dropna()
    if st.session_state.portfolios:
        for n in list(st.session_state.portfolios.keys()):
            if st.sidebar.button(n, use_container_width=True):
                st.session_state.active_portfolio_name = n
                st.rerun()

active = st.session_state.get('active_portfolio_name')
if not active: st.stop()

st.markdown(f'<div class="master-title">{active.replace(".csv","")} Analysis</div>', unsafe_allow_html=True)
t_dash, t_edit = st.tabs(["📊 Dashboard", "✏️ Edit Positions"])

with t_dash:
    df = st.session_state.portfolios[active].copy()
    df['Shares'] = df['Shares'].apply(clean_numeric)
    
    with st.spinner("Bulk Syncing Dividends..."):
        meta = get_cloud_data_v7(df['Ticker'].unique().tolist())
    
    df['Price'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('price', 0))
    df['Div'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('div', 0))
    df['Market Value'] = df['Shares'] * df['Price']
    df['Annual Income'] = df['Shares'] * df['Div']
    df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
    df['Safety'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('safety', 'Tier 2: ⚠️ STABLE'))
    df['Freq'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('freq', 4))
    df['Ex_Date'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('ex_date'))

    m1, m2, m3 = st.columns(3)
    m1.metric("Account Balance", f"${df['Market Value'].sum():,.0f}")
    m2.metric("Annual Income", f"${df['Annual Income'].sum():,.2f}")
    m3.metric("Yield", f"{(df['Annual Income'].sum()/df['Market Value'].sum()*100) if df['Market Value'].sum()>0 else 0:.2f}%")

    st.divider()
    c1, c2, c3 = st.columns(3)
    
    def draw_pie_v7(pdf, val_col, label_col):
        def agg(g):
            s_g = g.sort_values(val_col, ascending=False).head(15)
            b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g[val_col])])
            return pd.Series({'Val': g[val_col].sum(), 'Hover': f"<b>Total: ${g[val_col].sum():,.2f}</b><br><br>{b}"})
        sum_df = pdf.groupby(label_col).apply(agg).reset_index()
        f = go.Figure(data=[go.Pie(labels=sum_df[label_col], values=sum_df['Val'], hole=0.5, customdata=sum_df['Hover'], hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>")])
        f.update_layout(height=550, margin=dict(t=20, b=50), hoverlabel=HOVER_STYLE)
        st.plotly_chart(f, use_container_width=True)

    with c1:
        st.subheader("Safety Rating")
        draw_pie_v7(df, "Annual Income", "Safety")
    with c2:
        st.subheader("10-Year Forecast")
        g = st.number_input("Growth %", value=6.0)
        proj = [df['Annual Income'].sum() * ((1 + g/100)**i) for i in range(11)]
        fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
        fig_g.update_layout(hoverlabel=HOVER_STYLE, height=400)
        st.plotly_chart(fig_g, use_container_width=True)
    with c3:
        st.subheader("Sector Allocation")
        draw_pie_v7(df, "Market Value", "Sector")

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

    st.subheader("Details")
    st.dataframe(df[['Ticker', 'Price', 'Market Value', 'Annual Income']].sort_values('Market Value', ascending=False).style.format({
        'Price': '${:,.2f}', 'Market Value': '${:,.0f}', 'Annual Income': '${:,.2f}'
    }), use_container_width=True, hide_index=True)
