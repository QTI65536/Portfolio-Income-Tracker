import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import time

# --- 1. CONFIG & STYLING (V10.1 NATIVE HTML + YIELD) ---
st.set_page_config(layout="wide", page_title="Income Portfolio Tracker by QTI")

st.markdown("""
    <style>
    /* Metric & Tab Scaling */
    [data-testid="stMetricLabel"] > div { font-size: 26px !important; font-weight: 800 !important; color: #333 !important; }
    [data-testid="stMetricValue"] > div { font-size: 52px !important; font-weight: 900 !important; color: #2c3e50 !important; }
    .stTabs [data-baseweb="tab"] p { font-size: 28px !important; font-weight: 700 !important; }

    /* Master UI Branding */
    .master-title { font-size: 52px !important; color: #2c3e50; font-weight: 900; border-bottom: 3px solid #2ecc71; padding-bottom: 10px; }
    .app-branding { font-size: 22px !important; color: #7f8c8d; font-weight: 400; margin-bottom: -10px; }

    /* BUTTON STYLING */
    .stButton > button, .stDownloadButton > button { 
        font-weight: 900 !important; font-size: 22px !important; border-radius: 8px !important;
        height: 3.8rem !important; max-width: 500px !important; text-transform: uppercase !important;
    }
    div[data-testid="stFormSubmitButton"] button { background-color: #2ecc71 !important; color: white !important; }
    div.stDownloadButton button { background-color: #3498db !important; color: white !important; }

    /* NATIVE HTML TABLE SCALING */
    .html-table-container { width: 100%; overflow-x: auto; }
    .gold-table { width: 100%; border-collapse: collapse; font-size: 22px !important; font-family: sans-serif; }
    .gold-table th { background-color: #f8f9fa; color: #2c3e50; font-size: 24px !important; text-align: left; padding: 16px; border-bottom: 3px solid #2ecc71; }
    .gold-table td { padding: 16px; border-bottom: 1px solid #dee2e6; color: #333; }
    .gold-table tr:hover { background-color: #f1f1f1; }
    .tk-bold { font-weight: 900; color: #2c3e50; }
    </style>
    """, unsafe_allow_html=True)

HOVER_STYLE = dict(bgcolor="white", font_size=22, font_family="Arial", bordercolor="#2ecc71")
HARDCODED_CEFS = {'ADX', 'AIO', 'ASGI', 'BME', 'BST', 'BUI', 'CSQ', 'DNP', 'EOS', 'ERH', 'GDV', 'GLU', 'GOF', 'NBXG',
                  'NIE', 'PCN', 'PDI', 'PDO', 'PDX', 'RFI', 'RLTY', 'RNP', 'RQI', 'STK', 'UTF', 'UTG'}


# --- 2. HELPERS ---
def clean_numeric(value):
    try:
        if pd.isna(value) or value == "": return 0.0
        return float(str(value).replace('$', '').replace(',', '').strip())
    except:
        return 0.0


def strip_ext(filename):
    return filename.rsplit('.', 1)[0] if '.' in filename else filename


# --- 3. DATA ENGINE (FULL FORENSIC) ---
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
            tk = yf.Ticker(t);
            info = tk.info
            div_rate = float(info.get('dividendRate') or 0)
            if div_rate == 0 and not div_history.empty:
                div_rate = float(div_history[div_history.index > (datetime.now() - timedelta(days=365))].sum())

            sumry = info.get('longBusinessSummary', '').lower()
            is_cef = t in HARDCODED_CEFS or any(kw in sumry for kw in ["closed-end", "statutory trust"])
            sector = "Closed-End Fund" if is_cef else (
                info.get('quoteType', 'Other') if info.get('quoteType') == "ETF" else info.get('sector', 'Other'))

            # Forensic Safety Engine
            red_flags = []
            if sector not in ["Closed-End Fund", "ETF"]:
                ind = info.get('industry', '').lower()
                ocf, capex = (info.get('operatingCashflow', 0) or 0), abs(info.get('capitalExpenditures', 0) or 0)
                ebitda, int_exp = (info.get('ebitda', 0) or 0), (info.get('interestExpense', 0) or 0)
                total_div = div_rate * info.get('sharesOutstanding', 1)
                if "reit" in ind or sector == "Real Estate":
                    affo = ocf - capex
                    if (total_div / affo if affo > 0 else 1.5) > 0.90: red_flags.append("AFFO")
                elif sector == "Utilities":
                    if (total_div / ocf if ocf > 0 else 1.5) > 0.85: red_flags.append("OCF")
                else:
                    if (info.get('payoutRatio', 0) or 0) > 0.75: red_flags.append("EPS")
                if ((info.get('debtToEquity', 0) or 0) / 100) > 2.5: red_flags.append("Debt")
                if int_exp > 0 and (ebitda / int_exp) < 2.0: red_flags.append("Coverage")

            tier = "Tier 1: ✅ SAFE" if len(red_flags) == 0 else (
                "Tier 2: ⚠️ STABLE" if len(red_flags) == 1 else "Tier 3: 🚨 RISK")
            meta[t] = {'price': curr_price, 'div': div_rate, 'freq': 12 if len(div_history[div_history > 0]) > 6 else 4,
                       'ex_date': int(div_history[div_history > 0].index[-1].timestamp()) if not div_history[
                           div_history > 0].empty else None, 'sector': sector, 'safety': tier}
            time.sleep(0.05)
        except:
            meta[t] = {'price': 0.0, 'div': 0.0, 'freq': 4, 'ex_date': None, 'sector': 'Unknown',
                       'safety': 'Tier 3: 🚨 RISK'}
    return meta


# --- 4. SESSION STATE & SIDEBAR ---
if 'portfolios' not in st.session_state:
    st.session_state.portfolios = {}
    if os.path.exists("Sample Portfolio.csv"):
        try:
            sdf = pd.read_csv("Sample Portfolio.csv");
            sdf.columns = sdf.columns.str.strip()
            sdf['Shares'] = sdf['Shares'].apply(clean_numeric);
            sdf['Avg Cost'] = sdf['Avg Cost'].apply(clean_numeric)
            st.session_state.portfolios["Sample Portfolio.csv"] = sdf[["Ticker", "Shares", "Avg Cost"]].dropna()
            st.session_state.active_portfolio_name = "Sample Portfolio.csv"
        except:
            pass

with st.sidebar:
    st.header("📂 Portfolio Vault")
    up = st.file_uploader("Upload CSV Files", type="csv", accept_multiple_files=True)
    if up:
        for f in up:
            if f.name not in st.session_state.portfolios:
                d = pd.read_csv(f);
                d.columns = d.columns.str.strip()
                d['Shares'] = d['Shares'].apply(clean_numeric);
                d['Avg Cost'] = d['Avg Cost'].apply(clean_numeric)
                st.session_state.portfolios[f.name] = d[["Ticker", "Shares", "Avg Cost"]].dropna()
                st.session_state.active_portfolio_name = f.name
    if st.session_state.portfolios:
        st.write("---")
        for n in list(st.session_state.portfolios.keys()):
            if st.sidebar.button(
                    f"📍 {strip_ext(n)}" if n == st.session_state.get('active_portfolio_name') else strip_ext(n),
                    use_container_width=True):
                st.session_state.active_portfolio_name = n;
                st.rerun()

# --- 5. MAIN UI ---
st.markdown(f'<div class="app-branding">Income Portfolio Tracker by QTI (v10.1)</div>', unsafe_allow_html=True)
active = st.session_state.get('active_portfolio_name')

if not active:
    st.markdown('<div class="master-title">Welcome to Income Tracker</div>', unsafe_allow_html=True)
    st.markdown(
        """### 🚀 Getting Started:\n1. **Upload your Portfolio:** Use the sidebar on the left.\n2. **Required Format:** Ticker, Shares, Avg Cost.""")
    st.stop()

st.markdown(f'<div class="master-title">Portfolio: {strip_ext(active)}</div>', unsafe_allow_html=True)
t_dash, t_edit = st.tabs(["📊 Dashboard & Analytics", "✏️ Edit Positions"])

with t_edit:
    df_edit = st.session_state.portfolios[active]
    st.subheader("📁 Portfolio Settings")
    new_name = st.text_input("Rename Portfolio", value=strip_ext(active)).strip()
    if new_name and new_name != strip_ext(active):
        new_key = f"{new_name}.csv"
        st.session_state.portfolios[new_key] = st.session_state.portfolios.pop(active)
        st.session_state.active_portfolio_name = new_key;
        st.rerun()

    st.divider()
    st.subheader("➕ Add / Update Position")
    with st.form("entry", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        nt = c1.text_input("Ticker").upper().strip()
        ns = c2.number_input("Shares", min_value=0.0);
        nc = c3.number_input("Avg Cost", min_value=0.0)
        if st.form_submit_button("COMMIT TO PORTFOLIO"):
            if nt:
                if nt in df_edit['Ticker'].values:
                    df_edit.loc[df_edit['Ticker'] == nt, ['Shares', 'Avg Cost']] = [ns, nc]
                else:
                    st.session_state.portfolios[active] = pd.concat(
                        [df_edit, pd.DataFrame([{"Ticker": nt, "Shares": ns, "Avg Cost": nc}])], ignore_index=True)
                st.rerun()

    st.divider()
    st.subheader("📋 Inventory Management")
    csv_data = df_edit.to_csv(index=False).encode('utf-8')
    st.download_button(f"💾 SAVE {strip_ext(active).upper()} CSV", data=csv_data, file_name=f"{strip_ext(active)}.csv",
                       mime='text/csv')

    st.write("")
    to_remove = []
    cols = st.columns([1, 2, 2, 2])
    cols[0].write("**Select**");
    cols[1].write("**Ticker**");
    cols[2].write("**Shares**");
    cols[3].write("**Avg Cost**")
    for idx, row in df_edit.iterrows():
        r = st.columns([1, 2, 2, 2])
        if r[0].checkbox("", key=f"rm_{idx}"): to_remove.append(idx)
        r[1].write(f"**{row['Ticker']}**");
        r[2].write(f"{row['Shares']:,.2f}");
        r[3].write(f"${row['Avg Cost']:,.2f}")
    if to_remove and st.button(f"🗑️ DELETE SELECTED ({len(to_remove)})", type="primary"):
        st.session_state.portfolios[active] = df_edit.drop(to_remove);
        st.rerun()

with t_dash:
    df = st.session_state.portfolios[active].copy()
    if not df.empty:
        with st.spinner("Syncing Live Data..."):
            meta = get_unified_data(df['Ticker'].unique().tolist())
        df['Price'] = df['Ticker'].map(lambda x: float(meta.get(x, {}).get('price', 0)))
        df['Div'] = df['Ticker'].map(lambda x: float(meta.get(x, {}).get('div', 0)))
        df['Portfolio Value'] = df['Shares'] * df['Price']
        df['Income'] = df['Shares'] * df['Div']
        df['Yield'] = (df['Div'] / df['Price'].replace(0, 1)) * 100
        df['Sector'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('sector', 'Other'))
        df['Safety'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('safety', 'Tier 2'))
        df['Freq'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('freq', 4))
        df['Ex_Date'] = df['Ticker'].map(lambda x: meta.get(x, {}).get('ex_date'))

        m1, m2, m3, m4 = st.columns(4)
        total_mv, total_inc = df['Portfolio Value'].sum(), df['Income'].sum()
        m1.metric("Portfolio Value", f"${total_mv:,.0f}")
        m2.metric("Annual Income", f"${total_inc:,.2f}")
        m3.metric("Div. Yield", f"{(total_inc / total_mv * 100) if total_mv > 0 else 0:.2f}%")
        m4.metric("YOC",
                  f"{(total_inc / (df['Shares'] * df['Avg Cost']).sum() * 100) if (df['Shares'] * df['Avg Cost']).sum() > 0 else 0:.2f}%")

        st.divider();
        c1, c2, c3 = st.columns(3)


        def draw_donut(pdf, val_col, label_col, total_overall, hole=0.5):
            def agg(g):
                s_g = g.sort_values(val_col, ascending=False).head(15);
                b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g[val_col])])
                perc = (g[val_col].sum() / total_overall * 100) if total_overall > 0 else 0
                return pd.Series({'Val': g[val_col].sum(),
                                  'Hover': f"<b>{g.name}: {perc:.1f}%</b><br>Total: ${g[val_col].sum():,.2f}<br><br>{b}"})

            sum_df = pdf.groupby(label_col).apply(agg).reset_index()
            f = go.Figure(data=[go.Pie(labels=sum_df[label_col], values=sum_df['Val'], hole=hole, marker=dict(
                colors=['#2ecc71', '#f1c40f', '#e74c3c'] if label_col == 'Safety' else px.colors.qualitative.Pastel),
                                       customdata=sum_df['Hover'],
                                       hovertemplate="<b>%{customdata}</b><extra></extra>")])
            f.update_layout(height=600, margin=dict(t=30, b=80), hoverlabel=HOVER_STYLE)
            st.plotly_chart(f, use_container_width=True)


        with c1:
            st.subheader("Dynamic Safety Rating"); draw_donut(df, "Income", "Safety", total_inc, hole=0.6)
        with c2:
            st.subheader("10-Year Income Forecast")
            g_rate = st.number_input("Growth %", value=6.0, step=0.5)
            proj = [total_inc * ((1 + g_rate / 100) ** i) for i in range(11)]
            fig_g = px.area(x=[datetime.now().year + i for i in range(11)], y=proj)
            fig_g.update_layout(hoverlabel=HOVER_STYLE, height=450);
            fig_g.update_traces(hovertemplate="<b>Year: %{x}</b><br>Income: $%{y:,.2f}<extra></extra>")
            st.plotly_chart(fig_g, use_container_width=True)
        with c3:
            st.subheader("Sector Allocation")
            v_t = st.radio("Toggle View:", ["Portfolio Value", "Annual Income"], horizontal=True)
            draw_donut(df, "Portfolio Value" if v_t == "Portfolio Value" else "Income", "Sector",
                       total_mv if v_t == "Portfolio Value" else total_inc)

        st.divider();
        st.subheader("📅 Monthly Income Distribution")
        cal_list = []
        mnths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for _, r in df.iterrows():
            if r['Income'] > 0:
                f, ex = int(r['Freq']), r['Ex_Date']
                start = datetime.fromtimestamp(ex).month if ex else (1 if f == 12 else 3)
                for i in range(f):
                    idx = (start + (i * (12 // f)) - 1) % 12
                    cal_list.append(
                        {'Ticker': r['Ticker'], 'Month': mnths[idx], 'Income': r['Income'] / f, 'Sort': idx})
        if cal_list:
            c_df = pd.DataFrame(cal_list)


            def m_stats(g):
                s_g = g.sort_values('Income', ascending=False).head(15);
                b = "<br>".join([f"• {t}: <b>${amt:,.2f}</b>" for t, amt in zip(s_g['Ticker'], s_g['Income'])])
                return pd.Series({'Total': g['Income'].sum(),
                                  'Break': f"<b>Monthly Total: ${g['Income'].sum():,.2f}</b><br><br>{b}"})


            c_sum = c_df.groupby(['Month', 'Sort']).apply(m_stats).reset_index().sort_values('Sort')
            fig_c = go.Figure(data=[
                go.Bar(x=c_sum['Month'], y=c_sum['Total'], text=c_sum['Total'], texttemplate='$%{text:.2s}',
                       customdata=c_sum['Break'], hovertemplate="<b>%{x}</b><br>%{customdata}<extra></extra>")])
            fig_c.update_layout(hoverlabel=HOVER_STYLE, height=550);
            st.plotly_chart(fig_c, use_container_width=True)

        st.write("---");
        st.subheader("📋 Detailed Analytics")
        # NATIVE HTML TABLE (WITH YIELD COLUMN)
        df_disp = df[['Ticker', 'Sector', 'Safety', 'Price', 'Yield', 'Portfolio Value', 'Income']].sort_values(
            'Portfolio Value', ascending=False)
        html = "<div class='html-table-container'><table class='gold-table'><thead><tr>"
        html += "<th>Ticker</th><th>Sector</th><th>Safety</th><th>Price</th><th>Yield</th><th>Portfolio Value</th><th>Income</th></tr></thead><tbody>"
        for _, r in df_disp.iterrows():
            html += f"<tr><td class='tk-bold'>{r['Ticker']}</td><td>{r['Sector']}</td><td>{r['Safety']}</td><td>${r['Price']:,.2f}</td><td>{r['Yield']:.2f}%</td><td>${r['Portfolio Value']:,.0f}</td><td>${r['Income']:,.2f}</td></tr>"
        html += "</tbody></table></div>"
        st.markdown(html, unsafe_allow_html=True)
