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
    .app-branding { font-size: 22px !important; color: #7f8c8d; font-weight: 400; margin-bottom: -10px; }
    .master-title { 
        font-size: 52px !important; 
        color: #2c3e50; 
        font-weight: 900;
        margin-bottom: 10px;
        border-bottom: 3px solid #2ecc71;
        padding-bottom: 10px;
    }
    .stDataFrame { font-size: 18px !important; }
    </style>
    """, unsafe_allow_html=True)

HOVER_STYLE = dict(bgcolor="white", font_size=22, font_family="Arial", bordercolor="#2ecc71")

# --- DATA ENGINE (ARCHITECT OPTIMIZED) ---
@st.cache_data(ttl=3600)
def get_cloud_data(tickers):
    if not tickers: return {}
    
    # Bulk Download to flatten Multi-Index
    raw_data = yf.download(tickers, period="1d", auto_adjust=True)
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
            
            div = info.get('dividendRate') or 0
            if div == 0:
                h = tk.dividends
                div = h.last('365D').sum() if not h.empty else 0
            
            # Payout Frequency Logic for Calendar
            last_div = info.get('lastDividendValue') or 0
            freq = 12 if (div/last_div > 10 if last_div > 0 else False) else 4
            ex_date = info.get('exDividendDate')

            # Safety Logic
            payout = info.get('payoutRatio', 0) or 0
            tier = "Tier 1: ✅ SAFE" if payout < 0.75 else ("Tier 2: ⚠️ STABLE" if payout < 0.90 else "Tier 3: 🚨 RISK")
            
            meta[t] = {
                'price': prices.get(t, 0),
                'div': div,
                'sector': info.get('sector', 'Other'),
                'name': info.get('shortName', t),
                'safety': tier,
                'yield': (div / prices.get(t, 1)) if prices.get(t, 0) > 0 else 0,
                'freq': freq,
                'ex_date': ex_date
            }
        except:
            meta[t] = {'price': prices.get(t, 0), 'div': 0, 'sector': 'Other', 'name': t, 'safety': 'Tier 3: 🚨 RISK', 'yield': 0, 'freq': 4, 'ex_date': None}
    return meta

def clean_numeric(value):
    try: return float(str(value).replace('$', '').replace(',', '').strip())
    except: return 0.0

# --- SESSION STATE ---
if 'portfolios' not in st.session_state:
    st.session_state.portfolios = {}
    if os.path.exists("Sample Portfolio.csv"):
        try:
            df = pd.read_csv("Sample Portfolio.csv")
            df.columns = df.columns.str.strip()
            df = df[["Ticker", "Shares", "Avg Cost"]].dropna()
            df['Shares'] = df['Shares'].apply(clean_numeric)
            df['Avg Cost'] = df['Avg Cost'].apply(clean_numeric)
            st.session_state.portfolios["Sample Portfolio.csv"] = df
            st.session_state.active_portfolio_name = "Sample Portfolio.csv"
        except: pass

# --- SIDEBAR ---
with st.sidebar:
    st.header("📂 Portfolio Vault")
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
            if st.sidebar.button(f"📍 {n.replace('.csv','')}" if n == st.session_state.get('active_portfolio_name') else n.replace('.csv',''), use_container_width=True):
                st.session_state.active_portfolio_name = n
                st.rerun()

# --- MAIN UI ---
st.markdown('<div class="app-branding">Income Portfolio Tracker by QTI</div>', unsafe_allow_html=True)
active = st.session_state.get('active_portfolio_name')
if not active: st.stop()

st.markdown(f'<div class="master-title">Portfolio: {active.replace(".csv","")}</div>', unsafe_allow_html=True)
t_dash, t_edit = st.tabs(["📊 Dashboard & Analytics", "✏️ Edit Positions"])

with t_edit:
    df_edit = st.session_state.portfolios[active]
    with st.form("edit_form"):
        c1, c2, c3 = st.columns(3)
        nt = c1.text_input("Ticker Symbol").upper()
        ns = c2.number_input("Shares", min_value=0.0)
        nc = c3.number_input("Avg Cost", min_value=0.0)
        if st.form_submit_button("Commit Changes"):
            if nt in df_edit['Ticker'].values:
                df_edit.loc[df_edit['Ticker']==nt, ['Shares','Avg Cost']] = [ns, nc]
            else:
                st.session_state.portfolios[active] = pd.concat([df_edit, pd.DataFrame([{"Ticker":nt, "Shares":ns, "Avg Cost":nc}])])
            st.rerun()
    st.dataframe(df_edit, use_container_width=True, hide_index=True)

with t_dash:
    df = st.session_state.portfolios[active].copy()
    if not df.empty:
        tickers = df['Ticker'].unique().tolist()
        with st.spinner("Syncing Live Data..."):
            meta = get_cloud_data(tickers)
        
        df['Price'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('price', 0))
        df['Div'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('div', 0))
        df['Yield'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('yield', 0))
        df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
        df['Safety'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('safety', 'Unknown'))
        df['Freq'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('freq', 4))
        df['Ex_Date'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('ex_date'))
        df['Market Value'] = df['Shares'] * df['Price']
        df['Annual Income'] = df['Shares'] * df['Div']
        
        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Account Balance", f"${df['Market Value'].sum():,.0f}")
        m2.metric("Annual Income", f"${df['Annual Income'].sum():,.0f}")
        m3.metric("Div. Yield", f"{(df['Annual Income'].sum()/df['Market Value'].sum()*100) if df['Market Value'].sum()>0 else 0:.2f}%")
        m4.metric("Yield on Cost", f"{(df['Annual Income'].sum()/(df['Shares']*df['Avg Cost']).sum()*100) if (df['Shares']*df['Avg Cost']).sum()>0 else 0:.2f}%")
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("Dynamic Safety Rating")
            fig_saf = px.pie(df, values='Annual Income', names='Safety', hole=0.6)
            fig_saf.update_layout(hoverlabel=HOVER_STYLE, margin=dict(t=20, b=20))
            fig_saf.update_traces(hovertemplate="<b>%{label}</b><br>Income: $%{value:,.2f}<extra></extra>")
            st.plotly_chart(fig_saf, use_container_width=True)
        with c2:
            st.subheader("10-Year Income Forecast")
            g = st.number_input("Growth Rate (%)", value=6.0, step=0.5)
            proj = [df['Annual Income'].sum() * ((1 + g/100)**i) for i in range(11)]
            fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
            fig_g.update_layout(hoverlabel=HOVER_STYLE, xaxis_title="Year", yaxis_title="Income ($)")
            fig_g.update_traces(hovertemplate="<b>Year: %{x}</b><br>Income: $%{y:,.2f}<extra></extra>")
            st.plotly_chart(fig_g, use_container_width=True)
        with c3:
            st.subheader("Sector Allocation")
            v_type = st.radio("View By:", ["Market Value", "Annual Income"], horizontal=True)
            fig_sec = px.pie(df, values=v_type, names='Sector', hole=0.5)
            fig_sec.update_layout(hoverlabel=HOVER_STYLE, margin=dict(t=20, b=20))
            fig_sec.update_traces(hovertemplate="<b>%{label}</b><br>Amount: $%{value:,.2f}<extra></extra>")
            st.plotly_chart(fig_sec, use_container_width=True)

        st.write("---")
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
            c_sum = c_df.groupby(['Month', 'Sort'])['Income'].sum().reset_index().sort_values('Sort')
            fig_c = px.bar(c_sum, x='Month', y='Income', text_auto='.2s')
            fig_c.update_layout(hoverlabel=HOVER_STYLE, height=500)
            fig_c.update_traces(hovertemplate="<b>%{x} Total: $%{y:,.2f}</b><extra></extra>")
            st.plotly_chart(fig_c, use_container_width=True)
            
        st.subheader("Detailed Analytics")
        st.dataframe(df[['Ticker', 'Sector', 'Safety', 'Price', 'Yield', 'Market Value', 'Annual Income']].sort_values('Market Value', ascending=False).style.format({
            'Price': '${:,.2f}', 'Yield': '{:.2%}', 'Market Value': '${:,.0f}', 'Annual Income': '${:,.2f}'
        }), use_container_width=True, hide_index=True)
