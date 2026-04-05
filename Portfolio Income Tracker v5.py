import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import time

# --- 1. CONFIG & STYLING ---
st.set_page_config(layout="wide", page_title="Income Portfolio Tracker by QTI")

st.markdown("""
    <style>
    /* Tab & Metric Font Sizes */
    .stTabs [data-baseweb="tab"] p { font-size: 28px !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] p { font-size: 24px !important; font-weight: 800 !important; color: #333 !important; }
    [data-testid="stMetricValue"] { font-size: 48px !important; }
    
    /* Sidebar Styling */
    [data-testid="stSidebar"] .stButton button { font-size: 20px !important; font-weight: 600 !important; }
    .stFileUploader label { font-size: 22px !important; font-weight: bold !important; }
    
    /* Master UI */
    .master-title { font-size: 52px !important; color: #2c3e50; font-weight: 900; border-bottom: 3px solid #2ecc71; padding-bottom: 10px; }
    .app-branding { font-size: 22px !important; color: #7f8c8d; font-weight: 400; margin-bottom: -10px; }
    .stDataFrame { font-size: 18px !important; }
    </style>
    """, unsafe_allow_html=True)

HOVER_STYLE = dict(bgcolor="white", font_size=22, font_family="Arial", bordercolor="#2ecc71")

HARDCODED_CEFS = {
    'ADX', 'AIO', 'ASGI', 'BME', 'BST', 'BUI', 'CSQ', 'DNP', 'EOS', 'ERH', 
    'GDV', 'GLU', 'GOF', 'NBXG', 'NIE', 'PCN', 'PDI', 'PDO', 'PDX', 'RFI', 
    'RLTY', 'RNP', 'RQI', 'STK', 'UTF', 'UTG'
}

# --- 2. HELPERS ---
def clean_numeric(value):
    try: return float(str(value).replace('$', '').replace(',', '').strip())
    except: return 0.0

def strip_ext(filename):
    return filename.rsplit('.', 1)[0] if '.' in filename else filename

# --- 3. DATA ENGINE ---
@st.cache_data(ttl=3600)
def get_unified_data(tickers):
    if not tickers: return {}
    raw_data = yf.download(tickers, period="1y", actions=True, auto_adjust=True, progress=False)
    
    meta = {}
    for t in tickers:
        try:
            t_data = raw_data.xs(t, level=1, axis=1) if len(tickers) > 1 else raw_data
            curr_price = float(t_data['Close'].iloc[-1])
            div_history = t_data['Dividends']
            
            tk = yf.Ticker(t)
            info = tk.info
            
            div_rate = float(info.get('dividendRate') or 0)
            if div_rate == 0 and not div_history.empty:
                div_rate = float(div_history[div_history.index > (datetime.now() - timedelta(days=365))].sum())
            
            quote_type = info.get('quoteType', '').upper()
            industry = info.get('industry', '').lower()
            summary = info.get('longBusinessSummary', '').lower()
            sector_raw = info.get('sector', 'Other')
            
            is_cef = t in HARDCODED_CEFS or any(kw in summary for kw in ["closed-end", "statutory trust", "management investment company"])
            sector = "Closed-End Fund" if is_cef else (quote_type if quote_type == "ETF" else sector_raw)
            
            # Safety Engine
            red_flags = []
            if sector not in ["Closed-End Fund", "ETF"]:
                if "reit" in industry or sector == "Real Estate":
                    affo = (info.get('operatingCashflow', 0) or 0) - abs(info.get('capitalExpenditures', 0) or 0)
                    payout = (div_rate * info.get('sharesOutstanding', 1)) / affo if affo > 0 else 1.5
                    if payout > 0.90: red_flags.append("High AFFO Payout")
                else:
                    payout = info.get('payoutRatio', 0) or 0
                    if payout > 0.75: red_flags.append("High EPS Payout")
                
                if (info.get('debtToEquity', 0) or 0) > 250: red_flags.append("High Leverage")
                ebitda, int_exp = info.get('ebitda', 0) or 0, info.get('interestExpense', 0) or 0
                if int_exp > 0 and (ebitda / int_exp) < 2.0: red_flags.append("Weak Interest Cov")

            tier = "Tier 1: ✅ SAFE" if len(red_flags) == 0 else ("Tier 2: ⚠️ STABLE" if len(red_flags) == 1 else "Tier 3: 🚨 RISK")
            
            pay_count = len(div_history[div_history > 0])
            freq = 12 if pay_count > 6 else 4
            latest_ex = int(div_history[div_history > 0].index[-1].timestamp()) if not div_history[div_history > 0].empty else None

            meta[t] = {
                'price': curr_price, 'div': div_rate, 'freq': freq, 'ex_date': latest_ex,
                'sector': sector, 'safety': tier, 'name': info.get('shortName', t)
            }
            time.sleep(0.1)
        except:
            meta[t] = {'price': 0.0, 'div': 0.0, 'freq': 4, 'ex_date': None, 'sector': 'Unknown', 'safety': 'Tier 3: 🚨 RISK'}
    return meta

# --- 4. SESSION STATE ---
if 'portfolios' not in st.session_state:
    st.session_state.portfolios = {}
    if os.path.exists("Sample Portfolio.csv"):
        try:
            sdf = pd.read_csv("Sample Portfolio.csv"); sdf.columns = sdf.columns.str.strip()
            sdf['Shares'] = sdf['Shares'].apply(clean_numeric); sdf['Avg Cost'] = sdf['Avg Cost'].apply(clean_numeric)
            st.session_state.portfolios["Sample Portfolio.csv"] = sdf[["Ticker", "Shares", "Avg Cost"]].dropna()
            st.session_state.active_portfolio_name = "Sample Portfolio.csv"
        except: pass

if 'deleted_files' not in st.session_state: st.session_state.deleted_files = set()

# --- 5. SIDEBAR (GOLD RESTORATION) ---
with st.sidebar:
    st.header("📂 Portfolio Vault")
    uploaded_files = st.file_uploader("Upload CSV Files", type=["csv"], accept_multiple_files=True)
    
    # Sync deleted files set
    current_uploader_names = [f.name for f in uploaded_files] if uploaded_files else []
    st.session_state.deleted_files = {name for name in st.session_state.deleted_files if name in current_uploader_names}
    
    if uploaded_files:
        for file in uploaded_files:
            if file.name not in st.session_state.portfolios and file.name not in st.session_state.deleted_files:
                try:
                    raw_df = pd.read_csv(file); raw_df.columns = raw_df.columns.str.strip()
                    clean_df = raw_df[["Ticker", "Shares", "Avg Cost"]].dropna(subset=['Ticker']).copy()
                    clean_df['Shares'] = clean_df['Shares'].apply(clean_numeric)
                    clean_df['Avg Cost'] = clean_df['Avg Cost'].apply(clean_numeric)
                    st.session_state.portfolios[file.name] = clean_df
                    if st.session_state.get('active_portfolio_name') is None: st.session_state.active_portfolio_name = file.name
                except: st.error(f"Error loading {file.name}")

    if st.session_state.portfolios:
        st.write("---")
        st.write("### Active Selection")
        for name in list(st.session_state.portfolios.keys()):
            col_sel, col_del = st.columns([4, 1])
            is_active = (name == st.session_state.get('active_portfolio_name'))
            btn_label = f"{'📍 ' if is_active else ''}{strip_ext(name)}"
            
            if col_sel.button(btn_label, key=f"sel_{name}", use_container_width=True):
                st.session_state.active_portfolio_name = name
                st.rerun()
                
            if col_del.button("🗑️", key=f"del_{name}"):
                st.session_state.deleted_files.add(name)
                st.session_state.portfolios.pop(name, None)
                remaining = list(st.session_state.portfolios.keys())
                st.session_state.active_portfolio_name = remaining[0] if remaining else None
                st.rerun()

# --- 6. MAIN UI ---
active = st.session_state.get('active_portfolio_name')
if not active:
    st.markdown('<div class="master-title">Welcome</div>', unsafe_allow_html=True)
    st.info("Vault is empty. Upload a CSV file in the sidebar to begin.")
    st.stop()

st.markdown('<div class="app-branding">Income Portfolio Tracker by QTI</div>', unsafe_allow_html=True)
st.markdown(f'<div class="master-title">Portfolio: {strip_ext(active)}</div>', unsafe_allow_html=True)

t_dash, t_edit = st.tabs(["📊 Dashboard & Analytics", "✏️ Edit Positions"])

with t_edit:
    df_edit = st.session_state.portfolios[active]
    st.subheader("➕ Quick Entry / Update")
    with st.form("edit_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        nt = c1.text_input("Ticker Symbol").upper()
        ns = c2.number_input("Shares", min_value=0.0)
        nc = c3.number_input("Avg Cost", min_value=0.0)
        if st.form_submit_button("Commit to Portfolio"):
            if nt in df_edit['Ticker'].values: df_edit.loc[df_edit['Ticker']==nt, ['Shares','Avg Cost']] = [ns, nc]
            else: st.session_state.portfolios[active] = pd.concat([df_edit, pd.DataFrame([{"Ticker":nt, "Shares":ns, "Avg Cost":nc}])])
            st.rerun()
    st.divider()
    st.dataframe(df_edit, use_container_width=True, hide_index=True)

with t_dash:
    df = st.session_state.portfolios[active].copy()
    if not df.empty:
        with st.spinner("Syncing Golden Master Engines..."):
            meta = get_unified_data(df['Ticker'].unique().tolist())
        
        df['Price'] = df['Ticker'].map(lambda x: float(meta.get(x, {}).get('price', 0)))
        df['Div'] = df['Ticker'].map(lambda x: float(meta.get(x, {}).get('div', 0)))
        df['MV'] = df['Shares'] * df['Price']
        df['Income'] = df['Shares'] * df['Div']
        df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
        df['Safety'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('safety', 'Tier 2: ⚠️ STABLE'))
        df['Freq'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('freq', 4))
        df['Ex_Date'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('ex_date'))

        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Account Balance", f"${df['MV'].sum():,.0f}")
        m2.metric("Annual Income", f"${df['Income'].sum():,.2f}")
        m3.metric("Div. Yield", f"{(df['Income'].sum()/df['MV'].sum()*100) if df['MV'].sum()>0 else 0:.2f}%")
        m4.metric("Yield on Cost", f"{(df['Income'].sum()/(df['Shares']*df['Avg Cost']).sum()*100) if (df['Shares']*df['Avg Cost']).sum()>0 else 0:.2f}%")

        st.divider()
        c1, c2, c3 = st.columns(3)

        def draw_donut(pdf, val_col, label_col, hole=0.5):
            def agg(g):
                s_g = g.sort_values(val_col, ascending=False).head(15)
                b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g[val_col])])
                return pd.Series({'Val': g[val_col].sum(), 'Hover': f"<b>Total: ${g[val_col].sum():,.2f}</b><br><br>{b}"})
            sum_df = pdf.groupby(label_col).apply(agg).reset_index()
            colors = ['#2ecc71', '#f1c40f', '#e74c3c'] if label_col == 'Safety' else px.colors.qualitative.Pastel
            f = go.Figure(data=[go.Pie(labels=sum_df[label_col], values=sum_df['Val'], hole=hole, marker=dict(colors=colors), customdata=sum_df['Hover'], hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>")])
            f.update_layout(height=600, margin=dict(t=30, b=80), hoverlabel=HOVER_STYLE)
            st.plotly_chart(f, use_container_width=True)

        with c1:
            st.subheader("Dynamic Safety Rating")
            draw_donut(df, "Income", "Safety", hole=0.6)
        with c2:
            st.subheader("10-Year Income Forecast")
            g = st.number_input("Growth %", value=6.0, step=0.5)
            proj = [df['Income'].sum() * ((1 + g/100)**i) for i in range(11)]
            fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
            fig_g.update_layout(hoverlabel=HOVER_STYLE, height=450)
            fig_g.update_traces(hovertemplate="<b>Year: %{x}</b><br>Income: $%{y:,.2f}<extra></extra>")
            st.plotly_chart(fig_g, use_container_width=True)
        with c3:
            st.subheader("Sector Allocation")
            v_toggle = st.radio("Toggle View:", ["Market Value", "Annual Income"], horizontal=True)
            draw_donut(df, "MV" if v_toggle == "Market Value" else "Income", "Sector")

        st.divider()
        st.subheader("📅 Monthly Income Distribution")
        cal_list = []
        mnths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for _, r in df.iterrows():
            if r['Income'] > 0:
                f, ex = int(r['Freq']), r['Ex_Date']
                start = datetime.fromtimestamp(ex).month if ex else (1 if f==12 else 3)
                for i in range(f):
                    idx = (start + (i * (12//f)) - 1) % 12
                    cal_list.append({'Ticker': r['Ticker'], 'Month': mnths[idx], 'Income': r['Income']/f, 'Sort': idx})
        if cal_list:
            c_df = pd.DataFrame(cal_list)
            def m_stats(g):
                s_g = g.sort_values('Income', ascending=False).head(15)
                b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g['Income'])])
                return pd.Series({'Total': g['Income'].sum(), 'Break': f"<b>Monthly Total: ${g['Income'].sum():,.2f}</b><br><br>{b}"})
            c_sum = c_df.groupby(['Month', 'Sort']).apply(m_stats).reset_index().sort_values('Sort')
            fig_c = go.Figure(data=[go.Bar(x=c_sum['Month'], y=c_sum['Total'], text=c_sum['Total'], texttemplate='$%{text:.2s}', customdata=c_sum['Break'], hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>")])
            fig_c.update_layout(hoverlabel=HOVER_STYLE, height=550)
            st.plotly_chart(fig_c, use_container_width=True)

        st.subheader("Detailed Analytics")
        df['Yield'] = df['Div'] / df['Price'].replace(0, 1)
        st.dataframe(df[['Ticker', 'Sector', 'Safety', 'Price', 'Yield', 'MV', 'Income']].sort_values('MV', ascending=False).style.format({
            'Price': '${:,.2f}', 'Yield': '{:.2%}', 'MV': '${:,.0f}', 'Income': '${:,.2f}'
        }), use_container_width=True, hide_index=True)
