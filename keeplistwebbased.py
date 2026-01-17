import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
import pandas as pd
from datetime import datetime
import time
import requests

# --- CONFIGURATION ---
SHEET_NAME = "Pro Stock Manager DB"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

st.set_page_config(page_title="Pro Stock Manager", layout="wide", page_icon="🚀")

# ==============================================================================
#                           THEME & SESSION
# ==============================================================================
if 'dark_mode' not in st.session_state: st.session_state.dark_mode = False
if 'edit_data' not in st.session_state: st.session_state.edit_data = None

# TRACK PREVIOUS ALERTS TO PREVENT REPEATED POPUPS
if 'previous_alerts' not in st.session_state: st.session_state.previous_alerts = {}
if 'show_popup' not in st.session_state: st.session_state.show_popup = False
if 'popup_data' not in st.session_state: st.session_state.popup_data = pd.DataFrame()


def apply_theme(is_dark):
    if is_dark:
        return """
        <style>
        .stApp { background-color: #0e1117; color: #e0e0e0; }
        section[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] > div {
            background-color: #374151 !important; color: #ffffff !important; border-color: #4b5563 !important;
        }
        h1, h2, h3, p, label, .stMarkdown { color: #e0e0e0 !important; }
        div[data-testid="stMetricLabel"] { color: #9ca3af !important; }
        div[data-testid="stMetricValue"] { color: #ffffff !important; }
        </style>
        """
    else:
        return """
        <style>
        .stApp { background: linear-gradient(to right, #f8f9fa, #e9ecef); color: #333; }
        section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
        .main-header { font-family: 'Segoe UI', sans-serif; font-size: 1.2rem; font-weight: 700; color: #2c3e50; margin-bottom: 0px; }
        .sub-header { font-size: 0.9rem; color: #7f8c8d; }
        </style>
        """


# ==============================================================================
#                           GOOGLE SHEETS CONNECTION
# ==============================================================================
@st.cache_resource
def get_gsheet_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(creds)


def get_db():
    client = get_gsheet_client()
    try:
        sh = client.open(SHEET_NAME)
        return sh
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Spreadsheet '{SHEET_NAME}' not found! Please create it.")
        st.stop()


def get_col_letter(col_idx):
    col_idx += 1
    letter = ''
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        letter = chr(65 + remainder) + letter
    return letter


def init_db():
    sh = get_db()
    
    # 1. TRADES TAB
    try:
        ws_trades = sh.worksheet("Trades")
    except:
        ws_trades = sh.add_worksheet(title="Trades", rows="100", cols="20")
        ws_trades.append_row([
            "id", "stock_name", "cmp", "entry", "stop_loss", "target",
            "remark", "trade_type", "dv_analysis", "trade_zone",
            "trigger_date", "exit_date", "status", "last_alert"
        ])
    
    # Ensure "last_alert" column exists (Migration logic)
    headers = ws_trades.row_values(1)
    if "status" not in headers:
        ws_trades.update_cell(1, len(headers) + 1, "status")
        headers = ws_trades.row_values(1)
    if "last_alert" not in headers:
        ws_trades.update_cell(1, len(headers) + 1, "last_alert")

    # 2. PORTFOLIO TAB
    try:
        ws_port = sh.worksheet("Portfolio")
    except:
        ws_port = sh.add_worksheet(title="Portfolio", rows="100", cols="10")
        ws_port.append_row(["stock_name", "date", "stop_loss", "target", "actual_cost"])

    # 3. LINKS TAB
    try:
        ws_links = sh.worksheet("Links")
    except:
        ws_links = sh.add_worksheet(title="Links", rows="100", cols="5")
        ws_links.append_row(["stock_name", "link"])


# ==============================================================================
#                           TELEGRAM FUNCTION
# ==============================================================================
def send_telegram_message(message, test_mode=False):
    if "telegram" not in st.secrets:
        if test_mode: st.error("Secrets missing!")
        return

    try:
        bot_token = st.secrets["telegram"]["bot_token"]
        chat_ids = st.secrets["telegram"]["chat_id"]
        if not isinstance(chat_ids, list): chat_ids = [str(chat_ids)]

        for cid in chat_ids:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {"chat_id": cid, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload)

    except Exception as e:
        print(f"Telegram Error: {e}")


# ==============================================================================
#                           TRADES LOGIC
# ==============================================================================
def get_trades_df():
    sh = get_db()
    ws = sh.worksheet("Trades")
    data = ws.get_all_records()
    df = pd.DataFrame(data)

    if not df.empty:
        df['id'] = pd.to_numeric(df['id'], errors='coerce')
        cols = ['cmp', 'entry', 'stop_loss', 'target']
        for c in cols:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

        if 'status' not in df.columns: df['status'] = "Pending"
        if 'last_alert' not in df.columns: df['last_alert'] = ""
        
        df['status'] = df['status'].replace(r'^\s*$', 'Pending', regex=True).fillna('Pending')
        df['last_alert'] = df['last_alert'].fillna("")
        
    return df


def update_last_alert_in_db(trade_id, alert_msg):
    try:
        sh = get_db()
        ws = sh.worksheet("Trades")
        cell = ws.find(str(trade_id), in_column=1)
        if cell:
            headers = ws.row_values(1)
            try:
                col_idx = headers.index("last_alert") + 1
                ws.update_cell(cell.row, col_idx, alert_msg)
            except ValueError:
                pass 
    except Exception as e:
        print(f"DB Update Error: {e}")


def get_trendlyne_map():
    sh = get_db()
    try:
        ws = sh.worksheet("Links")
        data = ws.get_all_records()
        return {str(row['stock_name']).strip().upper(): row['link'] for row in data}
    except:
        return {}


def get_filtered_trades_advanced(f_status, f_zone, f_strat, f_pct):
    df = get_trades_df()
    if df.empty: return df

    if f_status != "All": df = df[df['status'] == f_status]
    if f_zone != "All": df = df[df['trade_zone'] == f_zone]
    if f_strat != "All": df = df[df['trade_type'] == f_strat]

    if df.empty: return df

    def calc_alert(row):
        # PRIORITY 1: Active
        if row['status'] == 'Active': return 0.0, "Trade is Active"
        
        # PRIORITY 2: Proximity
        if row['entry'] == 0: return 100, ""
        diff = abs(row['cmp'] - row['entry'])
        pct = (diff / row['entry']) * 100
        
        if pct <= 0.5: return pct, "Within 0.5% Range"
        elif pct <= 1.0: return pct, "Within 1% Range"
        return pct, ""

    df[['diff_pct', 'Alert']] = df.apply(lambda row: pd.Series(calc_alert(row)), axis=1)

    # --- UPDATED RANGE FILTER LOGIC ---
    if f_pct != "All":
        if f_pct == "0 - 0.5%":
            df = df[df['diff_pct'] <= 0.5]
        elif f_pct == "0.5% - 1%":
            df = df[(df['diff_pct'] > 0.5) & (df['diff_pct'] <= 1.0)]
        elif f_pct == "1% - 1.5%":
            df = df[(df['diff_pct'] > 1.0) & (df['diff_pct'] <= 1.5)]
        elif f_pct == "1.5% - 2%":
            df = df[(df['diff_pct'] > 1.5) & (df['diff_pct'] <= 2.0)]
        elif f_pct == "2% - 2.5%":
            df = df[(df['diff_pct'] > 2.0) & (df['diff_pct'] <= 2.5)]
        elif f_pct == "2.5% - 3%":
            df = df[(df['diff_pct'] > 2.5) & (df['diff_pct'] <= 3.0)]

    link_map = get_trendlyne_map()
    df['Trendlyne'] = df['stock_name'].apply(lambda x: link_map.get(str(x).replace('.NS','').strip().upper()))
    return df


def get_next_id(df):
    if df.empty or 'id' not in df.columns: return 1
    try: return int(pd.to_numeric(df['id'], errors='coerce').max()) + 1
    except: return 1


def add_trade(data):
    sh = get_db()
    ws = sh.worksheet("Trades")
    df = pd.DataFrame(ws.get_all_records())
    new_id = get_next_id(df)
    clean_stock = data['stock'].replace('.NS', '').replace('.BO', '')
    link = f"https://in.tradingview.com/chart/?symbol=NSE:{clean_stock}"
    
    headers = ws.row_values(1)
    
    row_data = {
        "id": new_id, "stock_name": data['stock'], "cmp": data['cmp'],
        "entry": data['entry'], "stop_loss": data['sl'], "target": data['tgt'],
        "remark": data['remark'], "trade_type": data['type'],
        "dv_analysis": link, "trade_zone": data['zone'],
        "trigger_date": "", "exit_date": "", "status": "Pending", "last_alert": ""
    }
    
    final_row = [row_data.get(h, "") for h in headers]
    ws.append_row(final_row)


def update_trade(trade_id, data):
    sh = get_db()
    ws = sh.worksheet("Trades")
    cell = ws.find(str(trade_id), in_column=1)
    if cell:
        clean_stock = data['stock'].replace('.NS', '').replace('.BO', '')
        link = f"https://in.tradingview.com/chart/?symbol=NSE:{clean_stock}"
        r = cell.row
        ws.update_cell(r, 2, data['stock'])
        ws.update_cell(r, 3, data['cmp'])
        ws.update_cell(r, 4, data['entry'])
        ws.update_cell(r, 5, data['sl'])
        ws.update_cell(r, 6, data['tgt'])
        ws.update_cell(r, 7, data['remark'])
        ws.update_cell(r, 8, data['type'])
        ws.update_cell(r, 9, link)
        ws.update_cell(r, 10, data['zone'])


def delete_trade(trade_id):
    sh = get_db()
    ws = sh.worksheet("Trades")
    cell = ws.find(str(trade_id), in_column=1)
    if cell: ws.delete_rows(cell.row)


def update_prices_logic():
    sh = get_db()
    ws = sh.worksheet("Trades")
    all_values = ws.get_all_values()
    if not all_values: return 0, 0, 0
    headers = all_values[0]
    rows = all_values[1:]
    
    try:
        col_map = {h: i for i, h in enumerate(headers)}
        idx_stock = col_map["stock_name"]
        idx_cmp = col_map["cmp"]
        idx_entry = col_map["entry"]
        idx_sl = col_map["stop_loss"]
        idx_tgt = col_map["target"]
        idx_trig = col_map["trigger_date"]
        idx_exit = col_map["exit_date"]
        idx_zone = col_map["trade_zone"]
        idx_status = col_map["status"]
    except KeyError: return 0, 0, 0
    
    updates = []
    count = 0; new_triggers = 0; new_exits = 0
    
    def to_float(val):
        try: return float(str(val).replace(',', '').strip())
        except: return 0.0

    for i, row in enumerate(rows):
        row_num = i + 2
        name = row[idx_stock]
        if not name: continue
        try:
            current_status = row[idx_status].strip() if len(row) > idx_status else "Pending"
            if not current_status: current_status = "Pending"
            if current_status in ["Target-Hit", "SL-Hit"]: continue

            tkr = name + ".NS" if not name.endswith((".NS", ".BO")) else name
            data = yf.Ticker(tkr).history(period="1d")
            if data.empty: continue
            cmp_val = round(data['Close'].iloc[-1], 2)
            
            entry = to_float(row[idx_entry])
            sl, tgt = to_float(row[idx_sl]), to_float(row[idx_tgt])
            zone = row[idx_zone].strip()
            
            new_status = current_status
            new_trig = row[idx_trig]
            new_exit = row[idx_exit]
            changed = False

            # Logic
            if new_status == "Pending":
                triggered = False
                if zone == "DEMAND" and cmp_val <= entry and entry > 0: triggered = True
                elif zone == "SUPPLY" and cmp_val >= entry and entry > 0: triggered = True
                
                if triggered:
                    new_status = "Active"
                    new_trig = datetime.now().strftime("%Y-%m-%d %H:%M")
                    new_triggers += 1; changed = True

            elif new_status == "Active":
                hit = False
                if zone == "DEMAND":
                    if cmp_val >= tgt and tgt > 0: new_status = "Target-Hit"; hit = True
                    elif cmp_val <= sl and sl > 0: new_status = "SL-Hit"; hit = True
                elif zone == "SUPPLY":
                    if cmp_val <= tgt and tgt > 0: new_status = "Target-Hit"; hit = True
                    elif cmp_val >= sl and sl > 0: new_status = "SL-Hit"; hit = True
                if hit:
                    new_exit = datetime.now().strftime("%Y-%m-%d %H:%M"); new_exits += 1; changed = True

            # Prepare Batch
            col_cmp_letter = get_col_letter(idx_cmp)
            updates.append({'range': f'{col_cmp_letter}{row_num}', 'values': [[cmp_val]]})
            
            if changed or row[idx_status].strip() == "":
                updates.append({'range': f'{get_col_letter(idx_status)}{row_num}', 'values': [[new_status]]})
            
            if changed:
                updates.append({'range': f'{get_col_letter(idx_trig)}{row_num}', 'values': [[new_trig]]})
                updates.append({'range': f'{get_col_letter(idx_exit)}{row_num}', 'values': [[new_exit]]})
                
            count += 1
        except Exception: pass
        
    if updates: ws.batch_update(updates)
    return count, new_triggers, new_exits


# ==============================================================================
#                           PORTFOLIO FUNCTIONS
# ==============================================================================
def get_portfolio_df():
    sh = get_db()
    ws = sh.worksheet("Portfolio")
    data = ws.get_all_records()
    return pd.DataFrame(data)

def save_portfolio_df(df):
    sh = get_db()
    ws = sh.worksheet("Portfolio")
    ws.clear()
    data_to_save = [df.columns.values.tolist()] + df.values.tolist()
    ws.update(range_name='A1', values=data_to_save)

def add_portfolio_stock(data):
    sh = get_db()
    ws = sh.worksheet("Portfolio")
    ws.append_row([data['name'], data['date'], data['sl'], data['target'], data['cost']])

def delete_portfolio_stock(stock_name):
    sh = get_db()
    ws = sh.worksheet("Portfolio")
    cell = ws.find(stock_name, in_column=1)
    if cell: ws.delete_rows(cell.row)


# ==============================================================================
#                           UI POPUP COMPONENT
# ==============================================================================
@st.dialog("🚨 Market Alerts")
def show_alert_popup(alert_df):
    st.warning("Updates Detected:")
    display_df = alert_df[['stock_name', 'Alert', 'trade_type', 'cmp']].reset_index(drop=True)
    st.dataframe(display_df, use_container_width=True)
    st.write("---")
    if st.button("OK, Dismiss", type="primary"):
        st.session_state.show_popup = False
        st.rerun()


# ==============================================================================
#                                   UI MAIN
# ==============================================================================
init_db()
if 'last_refresh' not in st.session_state: st.session_state.last_refresh = time.time()

with st.sidebar:
    st.markdown("### 🧭 Navigation")
    nav_option = st.radio("Main Navigation", ["Dashboard", "Live Trades", "Past Trades", "Portfolio Watch"], label_visibility="collapsed")
    st.markdown("---")
    
    # --- TEST BUTTON ---
    if st.button("📢 Test Telegram"):
        send_telegram_message("✅ *Test Message!* Bot is working.", test_mode=True)
    
    st.markdown("---")
    is_dark = st.toggle("🌙 Dark Mode", value=False)
    st.markdown(apply_theme(is_dark), unsafe_allow_html=True)
    st.markdown("---")

    if nav_option == "Portfolio Watch":
        st.header("➕ Add New Stock")
        with st.form("add_stock_form"):
            name = st.text_input("Stock Name")
            date = st.date_input("Date", value=datetime.now())
            sl = st.number_input("Stop Loss", value=0.0)
            target = st.number_input("Target", value=0.0)
            cost = st.number_input("Actual Cost", value=0.0)
            if st.form_submit_button("Add to Portfolio"):
                add_portfolio_stock({'name': name, 'date': str(date), 'sl': sl, 'target': target, 'cost': cost})
                st.success("Stock Added!")
                st.rerun()

# --- HEADER ---
col_h1, col_h2 = st.columns([6, 2])
with col_h1:
    sub_text = "Shared Cloud Database" if nav_option == "Portfolio Watch" else f"Viewing <b>{nav_option}</b>"
    st.markdown(f"""<div class='main-header'>📈 {nav_option}</div><div class='sub-header'>{sub_text}</div>""", unsafe_allow_html=True)

with col_h2:
    if nav_option != "Portfolio Watch":
        if st.button("↻ Cloud Update"):
            with st.spinner("Updating Prices & Status..."):
                c, trig, ex = update_prices_logic()
            st.toast(f"Checked {c} stocks. {trig} Activated, {ex} Closed.")
            st.session_state.last_refresh = time.time()
            time.sleep(1)
            st.rerun()

# --- ROUTER ---
if nav_option == "Dashboard":

    f1, f2, f3, f4 = st.columns(4)
    with f1: f_status = st.selectbox("Status", ["All", "Pending", "Active", "Target-Hit", "SL-Hit"], index=0)
    with f2: f_zone = st.selectbox("Zone", ["All", "DEMAND", "SUPPLY"], index=0)
    with f3: f_strat = st.selectbox("Strategy", ["All", "QIT", "MIT", "WIT", "DIT"], index=0)
    
    # --- UPDATED DROPDOWN OPTIONS ---
    pct_options = ["All", "0 - 0.5%", "0.5% - 1%", "1% - 1.5%", "1.5% - 2%", "2% - 2.5%", "2.5% - 3%"]
    with f4: f_pct = st.selectbox("% CMP Diff", pct_options, index=0)
    
    st.markdown("---")

    c1, c2 = st.columns(2)
    with c1:
        with st.expander("➕ Add Trade"):
            with st.form("add_form", clear_on_submit=True):
                fz = st.selectbox("Zone", ["DEMAND", "SUPPLY"])
                ft = st.selectbox("Type", ["QIT", "MIT", "WIT", "DIT"])
                fst = st.text_input("Stock")
                r1, r2, r3 = st.columns(3)
                fe, fs, ftg = r1.text_input("Entry"), r2.text_input("SL"), r3.text_input("Target")
                fc, fr = st.text_input("CMP"), st.text_input("Remark")
                if st.form_submit_button("Save") and fst:
                    add_trade({"stock": fst.upper(), "cmp": fc, "entry": fe, "sl": fs, "tgt": ftg, "remark": fr, "type": ft, "zone": fz})
                    with st.spinner("Processing..."): update_prices_logic()
                    st.success("Added!"); st.rerun()

    with c2:
        with st.expander("✏️ Edit Trade"):
            eid = st.number_input("ID", min_value=1, step=1)
            if st.button("Load"):
                df_all = get_trades_df()
                res = df_all[df_all['id'] == eid]
                if not res.empty: st.session_state.edit_data = res.iloc[0]
                else: st.error("Not Found")
            if st.session_state.edit_data is not None:
                t = st.session_state.edit_data
                with st.form("edit"):
                    st.caption(f"Edit: {t['stock_name']}")
                    ez = st.selectbox("Zone", ["DEMAND", "SUPPLY"], index=0 if t['trade_zone'] == "DEMAND" else 1)
                    et = st.selectbox("Type", ["QIT", "MIT", "WIT", "DIT"], index=["QIT", "MIT", "WIT", "DIT"].index(t['trade_type']))
                    est = st.text_input("Stock", t['stock_name'])
                    er1, er2, er3 = st.columns(3)
                    ee, es, etg = er1.text_input("Entry", t['entry']), er2.text_input("SL", t['stop_loss']), er3.text_input("Target", t['target'])
                    ec, er = st.text_input("CMP", t['cmp']), st.text_input("Remark", t['remark'])
                    if st.form_submit_button("Update"):
                        update_trade(t['id'], {"stock": est, "cmp": ec, "entry": ee, "sl": es, "tgt": etg, "remark": er, "type": et, "zone": ez})
                        st.session_state.edit_data = None; update_prices_logic(); st.success("Updated!"); st.rerun()

    df = get_filtered_trades_advanced(f_status, f_zone, f_strat, f_pct)

    if not df.empty:
        # --- ROBUST ALERT SYSTEM ---
        new_popup_alerts = []
        
        for idx, row in df.iterrows():
            curr_alert = row['Alert']
            last_alert = row['last_alert']
            
            if curr_alert != "" and curr_alert != last_alert:
                new_popup_alerts.append(row)
                
                tele_msg = (
                    f"🚀 *STOCK ALERT: {row['stock_name']}*\n"
                    f"⚠️ Status: {curr_alert}\n"
                    f"💰 CMP: {row['cmp']}\n"
                    f"🎯 Entry: {row['entry']}\n"
                    f"📊 Type: {row['trade_type']}"
                )
                send_telegram_message(tele_msg)
                
                update_last_alert_in_db(row['id'], curr_alert)

        if new_popup_alerts:
            st.session_state.popup_data = pd.DataFrame(new_popup_alerts)
            st.session_state.show_popup = True

        if st.session_state.show_popup and not st.session_state.popup_data.empty:
            show_alert_popup(st.session_state.popup_data)

        def highlight_alerts(row):
            styles = [''] * len(row)
            if row['Alert'] == "Trade is Active": return ['background-color: #4caf50; color: white; font-weight: bold'] * len(row)
            elif row['Alert'] == "Within 0.5% Range": return ['background-color: #ffeb3b; color: black'] * len(row)
            elif row['Alert'] == "Within 1% Range": return ['background-color: #90caf9; color: black'] * len(row)
            return styles

        st.dataframe(
            df[['id', 'Alert', 'trade_type', 'status', 'stock_name', 'trade_zone', 'cmp', 'entry', 'stop_loss', 'target', 'dv_analysis', 'Trendlyne']]
            .style.apply(highlight_alerts, axis=1),
            column_config={
                "dv_analysis": st.column_config.LinkColumn("View Chart", display_text="TradingView"),
                "Trendlyne": st.column_config.LinkColumn("Fundls", display_text="Trendlyne"),
                "cmp": st.column_config.NumberColumn(format="%.2f"),
                "entry": st.column_config.NumberColumn(format="%.2f")
            },
            use_container_width=True, hide_index=True
        )

        with st.expander("🗑 Delete"):
            did = st.number_input("Del ID", min_value=0)
            if st.button("Delete Trade"): delete_trade(did); st.rerun()
    else:
        st.info("No trades match your filters.")

elif nav_option == "Live Trades":
    df_live = get_trades_df()
    df_live = df_live[df_live['status'] == 'Active']
    if not df_live.empty:
        st.dataframe(df_live[['id', 'status', 'stock_name', 'cmp', 'entry', 'stop_loss', 'target', 'dv_analysis']], use_container_width=True, hide_index=True)
    else:
        st.success("No Active trades.")

elif nav_option == "Past Trades":
    df_past = get_trades_df()
    df_past = df_past[df_past['status'].isin(['Target-Hit', 'SL-Hit'])]
    if not df_past.empty:
        st.dataframe(df_past[['id', 'status', 'stock_name', 'cmp', 'stop_loss', 'target', 'exit_date']], use_container_width=True, hide_index=True)
    else:
        st.info("No History.")

elif nav_option == "Portfolio Watch":
    df_port = get_portfolio_df()
    edited_df = st.data_editor(df_port, num_rows="dynamic", use_container_width=True)
    if not edited_df.equals(df_port):
        save_portfolio_df(edited_df)
        st.toast("Saved!")
    with st.expander("Delete Stock"):
        if not df_port.empty:
            ds = st.selectbox("Stock", df_port['stock_name'].tolist())
            if st.button("Delete"): delete_portfolio_stock(ds); st.rerun()
