import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import time

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

# --- DATA ENGINE ---
@st.cache_data(ttl=3600)
def get_cloud_data(tickers):
    if not tickers: return {}
    raw_data = yf.download(tickers, period="1d", auto_adjust=True, progress=False)
    
    if len(tickers) > 1:
        prices_df = raw_data['Close']
    else:
        prices_df = raw_data[['Close']]
        prices_df.columns = tickers
    
    prices = prices_df.iloc[-1].to_dict()
    meta = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            div = float(info.get('dividendRate') or 0)
            if div == 0:
                h = tk.dividends
                div = float(h.last('365D').sum()) if not h.empty else 0.0
            
            # Frequency and Ex-Date for Calendar
            last_div = float(info.get('lastDividendValue') or 0)
            freq = 12 if (div/last_div > 10 if last_div > 0 else False) else 4
            ex_date = info.get('exDividendDate')
            
            meta[t] = {
                'price': float(prices.get(t, 0)), 
                'div': div, 
                'sector': info.get('sector', 'Other'),
                'safety': "Tier 1: ✅ SAFE" if info.get('payoutRatio', 0) < 0.8 else "Tier 2: ⚠️ STABLE",
                'freq': freq, 
                'ex_date': ex_date,
                'name': info.get('shortName', t)
            }
        except:
            meta[t] = {'price': float(prices.get(t, 0)), 'div': 0.0, 'sector': 'Other', 'safety': 'Tier 3: 🚨 RISK', 'freq': 4, 'ex_date': None, 'name': t}
    return meta

def clean_numeric(value):
    try:
        s = str(value).replace('$', '').replace(',', '').strip()
        return float(s) if s != "" else 0.0
    except: return 0.0

# --- SESSION STATE ---
if 'portfolios' not in st.session_state:
    st.session_state.portfolios = {}
    if os.path.exists("Sample Portfolio.csv"):
        try:
            df = pd.read_csv("Sample Portfolio.csv")
            df.columns = df.columns.str.strip()
            df = df[["Ticker", "Shares", "Avg Cost"]].dropna()
            df['Shares'] = df['Shares'].apply(clean_numeric); df['Avg Cost'] = df['Avg Cost'].apply(clean_numeric)
            st.session_state.portfolios["Sample Portfolio.csv"] = df
            st.session_state.active_portfolio_name = "Sample Portfolio.csv"
        except: pass

# --- SIDEBAR ---
with st.sidebar:
    st.header("📂 Vault")
    up = st.file_uploader("Upload", type="csv", accept_multiple_files=True)
    if up:
        for f in up:
            if f.name not in st.session_state.portfolios:
                d = pd.read_csv(f); d.columns = d.columns.str.strip()
                d['Shares'] = d['Shares'].apply(clean_numeric); d['Avg Cost'] = d['Avg Cost'].apply(clean_numeric)
                st.session_state.portfolios[f.name] = d[["Ticker", "Shares", "Avg Cost"]].dropna()
    
    if st.session_state.portfolios:
        for n in list(st.session_state.portfolios.keys()):
            if st.sidebar.button(n, use_container_width=True):
                st.session_state.active_portfolio_name = n
                st.rerun()

# --- MAIN ---
active = st.session_state.get('active_portfolio_name')
if not active: st.stop()
st.markdown(f'<div class="master-title">Portfolio: {active.replace(".csv","")}</div>', unsafe_allow_html=True)
t_dash, t_edit = st.tabs(["📊 Dashboard", "✏️ Edit"])

with t_edit:
    df_edit = st.session_state.portfolios[active]
    st.dataframe(df_edit, use_container_width=True, hide_index=True)

with t_dash:
    df = st.session_state.portfolios[active].copy()
    if not df.empty:
        with st.spinner("Syncing..."): meta = get_cloud_data(df['Ticker'].unique().tolist())
        
        df['Price'] = df['Ticker'].map(lambda x: float(meta.get(x, {}).get('price', 0)))
        df['Div'] = df['Ticker'].map(lambda x: float(meta.get(x, {}).get('div', 0)))
        df['Market Value'] = df['Shares'] * df['Price']
        df['Annual Income'] = df['Shares'] * df['Div']
        df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
        df['Safety'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('safety', 'Other'))
        df['Freq'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('freq', 4))
        df['Ex_Date'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('ex_date'))
        df['Yield'] = df['Div'] / df['Price'].replace(0, 1)

        # Metrics
        c_m = st.columns(4)
        c_m[0].metric("Balance", f"${df['Market Value'].sum():,.0f}")
        c_m[1].metric("Income", f"${df['Annual Income'].sum():,.0f}")
        c_m[2].metric("Yield", f"{(df['Annual Income'].sum()/df['Market Value'].sum()*100) if df['Market Value'].sum()>0 else 0:.2f}%")
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        
        # Helper for Charts with Ticker Breakdown
        def draw_breakdown_pie(pdf, title, val_col, label_col, hole=0.5):
            def agg(g):
                s_g = g.sort_values(val_col, ascending=False).head(15)
                b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g[val_col])])
                return pd.Series({'Val': g[val_col].sum(), 'Hover': f"<b>Total: ${g[val_col].sum():,.2f}</b><br><br>{b}"})
            
            sum_df = pdf.groupby(label_col).apply(agg).reset_index()
            f = go.Figure(data=[go.Pie(labels=sum_df[label_col], values=sum_df['Val'], hole=hole, customdata=sum_df['Hover'], hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>")])
            f.update_layout(height=650, margin=dict(t=50, b=100), hoverlabel=HOVER_STYLE)
            st.plotly_chart(f, use_container_width=True)

        with c1:
            st.subheader("Safety Rating")
            draw_breakdown_pie(df, "", "Annual Income", "Safety", hole=0.6)
        with c2:
            st.subheader("10-Year Income Forecast")
            growth = st.number_input("Growth %", value=6.0)
            proj = [df['Annual Income'].sum() * ((1 + growth/100)**i) for i in range(11)]
            fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
            fig_g.update_layout(hoverlabel=HOVER_STYLE, height=500, xaxis_title="Year", yaxis_title="Income ($)")
            fig_g.update_traces(hovertemplate="<b>Year: %{x}</b><br>Income: $%{y:,.2f}<extra></extra>")
            st.plotly_chart(fig_g, use_container_width=True)
        with c3:
            st.subheader("Sector Allocation")
            v = st.radio("By:", ["Market Value", "Annual Income"], horizontal=True)
            draw_breakdown_pie(df, "", v, "Sector")

        # RESTORED MONTHLY CALENDAR
        st.divider()
        st.subheader("📅 Monthly Income Distribution")
        cal_list = []
        mnths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for _, r in df.iterrows():
            if r['Annual Income'] > 0:
                f = int(r['Freq'])
                start = datetime.fromtimestamp(r['Ex_Date']).month if r['Ex_Date'] else (1 if f == 12 else 3)
                for i in range(f):
                    idx = (start + (i * (12//f)) - 1) % 12
                    cal_list.append({'Ticker': r['Ticker'], 'Month': mnths[idx], 'Income': r['Annual Income']/f, 'Sort': idx})
        
        if cal_list:
            c_df = pd.DataFrame(cal_list)
            def m_stats(g):
                s_g = g.sort_values('Income', ascending=False).head(15)
                b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g['Income'])])
                return pd.Series({'Total': g['Income'].sum(), 'Break': f"<b>Monthly Total: ${g['Income'].sum():,.2f}</b><br><br>{b}"})
            c_sum = c_df.groupby(['Month', 'Sort']).apply(m_stats).reset_index().sort_values('Sort')
            fig_c = go.Figure(data=[go.Bar(x=c_sum['Month'], y=c_sum['Total'], text=c_sum['Total'], texttemplate='$%{text:.2s}', customdata=c_sum['Break'], hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>")])
            fig_c.update_layout(hoverlabel=HOVER_STYLE, height=600, margin=dict(t=50, b=100))
            st.plotly_chart(fig_c, use_container_width=True)

        st.subheader("Detailed Analytics")
        st.dataframe(df[['Ticker', 'Sector', 'Safety', 'Price', 'Yield', 'Market Value', 'Annual Income']].sort_values('Market Value', ascending=False).style.format({
            'Price': '${:,.2f}', 'Yield': '{:.2%}', 'Market Value': '${:,.0f}', 'Annual Income': '${:,.2f}'
        }), use_container_width=True, hide_index=True)
