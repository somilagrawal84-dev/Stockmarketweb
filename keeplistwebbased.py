import streamlit as st
import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime
import time
import os

# --- CONFIGURATION ---
DB_NAME = "stocks.db"

st.set_page_config(page_title="Pro Stock Manager", layout="wide", page_icon="🚀")

# ==============================================================================
#                           THEME ENGINE
# ==============================================================================
if 'dark_mode' not in st.session_state: st.session_state.dark_mode = False


def apply_theme(is_dark):
    if is_dark:
        return """
        <style>
        .stApp { background-color: #0e1117; color: #e0e0e0; }
        section[data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #30363d; }
        .css-1r6slb0, .stDataFrame, .stForm, div[data-testid="stExpander"] { 
            background-color: #1f2937 !important; border: 1px solid #374151; border-radius: 8px;
        }
        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] > div {
            background-color: #374151 !important; color: #ffffff !important; border-color: #4b5563 !important;
        }
        ul[data-testid="stSelectboxVirtualDropdown"] { background-color: #374151 !important; }
        h1, h2, h3, p, label, .stMarkdown { color: #e0e0e0 !important; }
        div[data-testid="stMetricLabel"] { color: #9ca3af !important; }
        div[data-testid="stMetricValue"] { color: #ffffff !important; }
        div[data-testid="stDataFrame"] { background-color: #1f2937 !important; }
        </style>
        """
    else:
        return """
        <style>
        .stApp { background: linear-gradient(to right, #f8f9fa, #e9ecef); color: #333; }
        section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
        .css-1r6slb0, .stDataFrame, .stForm, div[data-testid="stExpander"] { 
            background-color: white !important; padding: 1rem; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); 
        }
        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] > div {
            background-color: #ffffff !important; color: #333333 !important;
        }
        .main-header { font-family: 'Segoe UI', sans-serif; font-size: 1.2rem; font-weight: 700; color: #2c3e50; margin-bottom: 0px; }
        .sub-header { font-size: 0.9rem; color: #7f8c8d; }
        </style>
        """


# ==============================================================================
#                           DATABASE FUNCTIONS (ALL SQLITE NOW)
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Table 1: Swing/Intraday Trades
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_name TEXT, cmp TEXT, entry TEXT, stop_loss TEXT, 
            target TEXT, remark TEXT, trade_type TEXT, dv_analysis TEXT, 
            trade_zone TEXT, trigger_date TEXT, exit_date TEXT
        )
    ''')

    # Table 2: Long Term Portfolio (Replaces Excel)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            stock_name TEXT, 
            date TEXT, 
            stop_loss REAL, 
            target REAL, 
            actual_cost REAL
        )
    ''')

    # Migration columns for trades table
    cursor.execute("PRAGMA table_info(trades)")
    cols = [c[1] for c in cursor.fetchall()]
    if "trigger_date" not in cols: cursor.execute("ALTER TABLE trades ADD COLUMN trigger_date TEXT")
    if "exit_date" not in cols: cursor.execute("ALTER TABLE trades ADD COLUMN exit_date TEXT")

    conn.commit()
    conn.close()


# --- TRADES FUNCTIONS ---
def get_trades(zone=None, trade_type=None, screen="DASHBOARD"):
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    if screen == "LIVE":
        query += " AND trigger_date IS NOT NULL AND trigger_date != '' AND (exit_date IS NULL OR exit_date = '')"
    elif screen == "PAST":
        query += " AND trigger_date IS NOT NULL AND trigger_date != '' AND exit_date IS NOT NULL AND exit_date != ''"

    if zone:
        query += " AND trade_zone = ?"
        params.append(zone)
    if trade_type and trade_type != "ANY":
        query += " AND trade_type = ?"
        params.append(trade_type)

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def get_trade_by_id(trade_id):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM trades WHERE id=?", conn, params=(int(trade_id),))
    conn.close()
    return df.iloc[0] if not df.empty else None


def add_trade(data):
    clean_stock = data['stock'].replace('.NS', '').replace('.BO', '')
    link = f"https://in.tradingview.com/chart/?symbol=NSE:{clean_stock}"
    conn = sqlite3.connect(DB_NAME)
    conn.execute(
        "INSERT INTO trades (stock_name, cmp, entry, stop_loss, target, remark, trade_type, trade_zone, dv_analysis, trigger_date, exit_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (data['stock'], data['cmp'], data['entry'], data['sl'], data['tgt'], data['remark'], data['type'], data['zone'],
         link, None, None))
    conn.commit()
    conn.close()


def update_trade(trade_id, data):
    clean_stock = data['stock'].replace('.NS', '').replace('.BO', '')
    link = f"https://in.tradingview.com/chart/?symbol=NSE:{clean_stock}"
    conn = sqlite3.connect(DB_NAME)
    conn.execute(
        "UPDATE trades SET stock_name=?, cmp=?, entry=?, stop_loss=?, target=?, remark=?, trade_type=?, trade_zone=?, dv_analysis=? WHERE id=?",
        (data['stock'], data['cmp'], data['entry'], data['sl'], data['tgt'], data['remark'], data['type'], data['zone'],
         link, int(trade_id)))
    conn.commit()
    conn.close()


def delete_trade(trade_id):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM trades WHERE id=?", (int(trade_id),))
    conn.commit()
    conn.close()


def update_prices_logic():
    conn = sqlite3.connect(DB_NAME)
    rows = conn.execute(
        "SELECT id, stock_name, entry, stop_loss, target, trigger_date, exit_date, trade_zone FROM trades").fetchall()
    count = 0;
    new_triggers = 0;
    new_exits = 0
    for rid, name, entry_price, sl_price, tgt_price, trig_date, ex_date, zone in rows:
        try:
            tkr = name + ".NS" if not name.endswith((".NS", ".BO")) else name
            data = yf.Ticker(tkr).history(period="1d")
            if data.empty: continue
            cmp_val = round(data['Close'].iloc[-1], 2)
            new_trig = trig_date;
            new_exit = ex_date
            c = float(cmp_val);
            e = float(entry_price) if entry_price else 0.0
            s = float(sl_price) if sl_price else 0.0;
            t = float(tgt_price) if tgt_price else 0.0

            if (not trig_date or trig_date == '') and e > 0:
                is_initiated = False
                if zone == "DEMAND" and c <= e:
                    is_initiated = True
                elif zone == "SUPPLY" and c >= e:
                    is_initiated = True
                if is_initiated: new_trig = datetime.now().strftime("%Y-%m-%d %H:%M"); new_triggers += 1

            if new_trig and (not ex_date or ex_date == '') and s > 0 and t > 0:
                is_exited = False
                if zone == "DEMAND":
                    if c <= s or c >= t: is_exited = True
                elif zone == "SUPPLY":
                    if c >= s or c <= t: is_exited = True
                if is_exited: new_exit = datetime.now().strftime("%Y-%m-%d %H:%M"); new_exits += 1

            conn.execute("UPDATE trades SET cmp=?, trigger_date=?, exit_date=? WHERE id=?",
                         (str(cmp_val), new_trig, new_exit, rid))
            count += 1
        except:
            pass
    conn.commit()
    conn.close()
    return count, new_triggers, new_exits


def get_stats():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT trade_zone FROM trades", conn)
    conn.close()
    return len(df), len(df[df['trade_zone'] == 'DEMAND']), len(df[df['trade_zone'] == 'SUPPLY'])


# --- NEW PORTFOLIO FUNCTIONS (SQLITE REPLACEMENT FOR EXCEL) ---
def load_portfolio_data():
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql("SELECT * FROM portfolio", conn)
        # Rename columns to match UI expectation if needed, or keep SQL names
        # SQL: stock_name, date, stop_loss, target, actual_cost
        df.columns = ['Stock Name', 'Date', 'Stop Loss', 'Target', 'Actual Cost']
    except:
        df = pd.DataFrame(columns=['Stock Name', 'Date', 'Stop Loss', 'Target', 'Actual Cost'])
    conn.close()
    return df


def save_portfolio_data(df):
    # Rename for SQL compatibility
    df_sql = df.copy()
    df_sql.columns = ['stock_name', 'date', 'stop_loss', 'target', 'actual_cost']
    conn = sqlite3.connect(DB_NAME)
    # Replace ensures we overwrite the table with current view (mimics Excel save)
    df_sql.to_sql('portfolio', conn, if_exists='replace', index=False)
    conn.close()


def add_portfolio_stock(data):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("INSERT INTO portfolio (stock_name, date, stop_loss, target, actual_cost) VALUES (?,?,?,?,?)",
                 (data['name'], data['date'], data['sl'], data['target'], data['cost']))
    conn.commit()
    conn.close()


def delete_portfolio_stock(stock_name):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM portfolio WHERE stock_name=?", (stock_name,))
    conn.commit()
    conn.close()


# ==============================================================================
#                                   INIT & SIDEBAR
# ==============================================================================
init_db()

if 'last_refresh' not in st.session_state: st.session_state.last_refresh = time.time()
if time.time() - st.session_state.last_refresh > 60:
    update_prices_logic()
    st.session_state.last_refresh = time.time()
    st.rerun()

with st.sidebar:
    st.markdown("### 🧭 Navigation")
    nav_option = st.radio("", ["Dashboard", "Live Trades", "Past Trades", "Portfolio Watch"],
                          label_visibility="collapsed")
    st.markdown("---")

    # THEME TOGGLE
    is_dark = st.toggle("🌙 Dark Mode", value=False)
    st.markdown(apply_theme(is_dark), unsafe_allow_html=True)
    st.markdown("---")

    if nav_option in ["Dashboard", "Live Trades", "Past Trades"]:
        st.markdown("### 🌪 Filters")
        c1, c2 = st.columns(2)
        with c1:
            filter_zone = st.radio("Zone", ["DEMAND", "SUPPLY"])
        with c2:
            filter_type = st.selectbox("Strategy", ["ANY", "QIT", "MIT", "WIT", "DIT"])
        st.markdown("---")
        tot, dem, sup = get_stats()
        st.markdown(f"**Total:** {tot} | **Buy:** {dem} | **Sell:** {sup}")

    elif nav_option == "Portfolio Watch":
        st.header("➕ Add New Stock")
        with st.form("add_stock_form"):
            name = st.text_input("Stock Name")
            date = st.date_input("Date", value=datetime.now())
            sl = st.number_input("Stop Loss", value=0.0)
            target = st.number_input("Target", value=0.0)
            cost = st.number_input("Actual Cost", value=0.0)
            if st.form_submit_button("Add to Portfolio"):
                add_portfolio_stock(
                    {'name': name, 'date': date.strftime('%Y-%m-%d'), 'sl': sl, 'target': target, 'cost': cost})
                st.success("Stock Added!")
                st.rerun()

# ==============================================================================
#                           HEADER
# ==============================================================================
col_h1, col_h2 = st.columns([6, 2])
with col_h1:
    sub_text = "Shared Portfolio Manager (Database)" if nav_option == "Portfolio Watch" else f"Viewing <b>{filter_zone}</b> trades | Strategy: <b>{filter_type}</b>"
    st.markdown(f"""<div class='main-header'>📈 {nav_option}</div><div class='sub-header'>{sub_text}</div>""",
                unsafe_allow_html=True)

with col_h2:
    if nav_option != "Portfolio Watch":
        c_refresh, c_timer = st.columns([1, 1])
        with c_refresh:
            if st.button("↻ Update"):
                c, trig, ex = update_prices_logic()
                st.toast(f"Updated {c}. {trig} Initiated, {ex} Closed.")
                st.session_state.last_refresh = time.time()
                time.sleep(1)
                st.rerun()
        with c_timer:
            time_left = 60 - int(time.time() - st.session_state.last_refresh)
            st.markdown(
                f"<div style='font-size:12px; color:{'#a0a0a0' if is_dark else 'gray'}; text-align:center; padding-top:5px;'>Auto: <b>{max(0, time_left)}s</b></div>",
                unsafe_allow_html=True)


# ==============================================================================
#                           VIEW FUNCTIONS
# ==============================================================================

def render_dashboard():
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📊 Total Trades", tot)
    m2.metric("🟢 Demand (Buy)", dem)
    m3.metric("🔴 Supply (Sell)", sup)
    m4.metric("⚡ Strategy", filter_type)
    st.markdown("---")

    c_exp1, c_exp2 = st.columns(2)
    with c_exp1:
        with st.expander("➕ Add New Trade", expanded=False):
            with st.form("add_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                f_zone = c1.selectbox("Zone", ["DEMAND", "SUPPLY"])
                f_type = c2.selectbox("Type", ["QIT", "MIT", "WIT", "DIT"])
                f_stock = st.text_input("Stock Name")
                r1, r2, r3 = st.columns(3)
                f_entry, f_sl, f_tgt = r1.text_input("Entry"), r2.text_input("SL"), r3.text_input("Target")
                f_cmp, f_remark = st.text_input("CMP (Optional)"), st.text_input("Remark")
                if st.form_submit_button("Save Trade", use_container_width=True) and f_stock:
                    add_trade({"stock": f_stock.upper(), "cmp": f_cmp, "entry": f_entry, "sl": f_sl, "tgt": f_tgt,
                               "remark": f_remark, "type": f_type, "zone": f_zone})
                    st.success("Saved!")
                    st.rerun()

    with c_exp2:
        with st.expander("✏️ Edit Trade", expanded=False):
            c_search, c_btn = st.columns([3, 1])
            edit_id = c_search.number_input("Trade ID", min_value=1, step=1, label_visibility="collapsed")
            if 'edit_data' not in st.session_state: st.session_state.edit_data = None
            if c_btn.button("Load"):
                t = get_trade_by_id(edit_id)
                if t is not None:
                    st.session_state.edit_data = t
                else:
                    st.error("Invalid ID")

            if st.session_state.edit_data is not None:
                t = st.session_state.edit_data
                with st.form(key=f"edit_form_{t['id']}"):
                    st.caption(f"Editing: {t['stock_name']}")
                    e1, e2 = st.columns(2)
                    e_zone = e1.selectbox("Zone", ["DEMAND", "SUPPLY"], index=0 if t['trade_zone'] == "DEMAND" else 1,
                                          key=f"e_zone_{t['id']}")
                    e_type = e2.selectbox("Type", ["QIT", "MIT", "WIT", "DIT"],
                                          index=["QIT", "MIT", "WIT", "DIT"].index(t['trade_type']),
                                          key=f"e_type_{t['id']}")
                    e_stock = st.text_input("Stock", value=t['stock_name'], key=f"e_stock_{t['id']}")
                    er1, er2, er3 = st.columns(3)
                    e_entry = er1.text_input("Entry", value=t['entry'], key=f"e_ent_{t['id']}")
                    e_sl = er2.text_input("SL", value=t['stop_loss'], key=f"e_sl_{t['id']}")
                    e_tgt = er3.text_input("Target", value=t['target'], key=f"e_tgt_{t['id']}")
                    e_cmp = st.text_input("CMP", value=t['cmp'], key=f"e_cmp_{t['id']}")
                    e_remark = st.text_input("Remark", value=t['remark'], key=f"e_rem_{t['id']}")
                    if st.form_submit_button("Update", use_container_width=True):
                        update_trade(t['id'], {"stock": e_stock.upper(), "cmp": e_cmp, "entry": e_entry, "sl": e_sl,
                                               "tgt": e_tgt, "remark": e_remark, "type": e_type, "zone": e_zone})
                        st.success("Updated!")
                        st.session_state.edit_data = None
                        time.sleep(1)
                        st.rerun()

    df = get_trades(filter_zone, filter_type, "DASHBOARD")
    for col in ['trigger_date', 'exit_date']:
        if col in df.columns: df[col] = df[col].fillna("").astype(str).replace(['None', 'nan'], '')
    if not df.empty:
        st.data_editor(df[['id', 'trade_zone', 'stock_name', 'cmp', 'entry', 'stop_loss', 'target', 'trigger_date',
                           'exit_date', 'dv_analysis']],
                       column_config={"dv_analysis": st.column_config.LinkColumn("Chart", display_text="View"),
                                      "trigger_date": st.column_config.TextColumn("Order Initiate"),
                                      "exit_date": st.column_config.TextColumn("SL/TGT Date"), "trade_zone": "Zone",
                                      "stock_name": "Stock",
                                      "cmp": st.column_config.NumberColumn("CMP", format="%.2f")},
                       hide_index=True, use_container_width=True, height=500, key="dash_table")
        with st.expander("🗑 Delete Trade"):
            cd1, cd2 = st.columns([1, 4])
            d_id = cd1.number_input("ID", min_value=0, label_visibility="collapsed")
            if cd2.button("Delete"): delete_trade(d_id); st.rerun()
    else:
        st.info("No active trades.")


def render_live():
    df = get_trades(filter_zone, filter_type, "LIVE")
    if 'trigger_date' in df.columns: df['trigger_date'] = df['trigger_date'].fillna("").astype(str)
    if not df.empty:
        st.data_editor(df[['id', 'trade_zone', 'stock_name', 'cmp', 'entry', 'stop_loss', 'target', 'trigger_date',
                           'dv_analysis']],
                       column_config={"dv_analysis": st.column_config.LinkColumn("Chart", display_text="View"),
                                      "trigger_date": st.column_config.TextColumn("Order Initiate Date"),
                                      "trade_zone": "Zone", "stock_name": "Stock",
                                      "cmp": st.column_config.NumberColumn("CMP", format="%.2f")},
                       hide_index=True, use_container_width=True, height=600, key="live_table")
    else:
        st.success("No live triggered trades at the moment.")


def render_past():
    df = get_trades(filter_zone, filter_type, "PAST")
    if 'exit_date' in df.columns: df['exit_date'] = df['exit_date'].fillna("").astype(str)

    def check_status(row):
        try:
            c, s, t = float(row['cmp']), float(row['stop_loss']), float(row['target'])
            if row['trade_zone'] == "DEMAND":
                return "❌ SL Hit" if c <= s else ("🎯 Target Hit" if c >= t else None)
            else:
                return "❌ SL Hit" if c >= s else ("🎯 Target Hit" if c <= t else None)
        except:
            return None

    if not df.empty:
        df['STATUS'] = df.apply(check_status, axis=1)
        st.data_editor(
            df[['id', 'trade_zone', 'stock_name', 'cmp', 'stop_loss', 'target', 'exit_date', 'STATUS', 'dv_analysis']],
            column_config={"dv_analysis": st.column_config.LinkColumn("Chart", display_text="View"),
                           "exit_date": st.column_config.TextColumn("SL/TGT Date"), "trade_zone": "Zone",
                           "stock_name": "Stock", "cmp": st.column_config.NumberColumn("CMP", format="%.2f")},
            hide_index=True, use_container_width=True, height=600, key="past_table")
    else:
        st.info("No past trades found.")


def render_portfolio():
    df_port = load_portfolio_data()
    col1, col2 = st.columns([1, 3])
    with col1:
        filter_on = st.toggle("Filter: Cost between SL and Target")

    display_df = df_port.copy()

    def get_status(row):
        try:
            return "In Range" if row['Stop Loss'] <= row['Actual Cost'] <= row['Target'] else "Out of Range"
        except:
            return "Error"

    display_df['Status'] = display_df.apply(get_status, axis=1)
    if filter_on: display_df = display_df[display_df['Status'] == "In Range"]

    st.write("💡 *Tip: You can edit values directly in the table below.*")
    edited_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, key="data_editor")

    if not filter_on:
        if not edited_df.equals(df_port):
            save_portfolio_data(edited_df)
            st.toast("Changes saved automatically!", icon="💾")
    else:
        st.info("Turn off filter to edit data.")

    with st.expander("🗑️ Delete Stock"):
        opts = df_port['Stock Name'].tolist()
        if opts:
            s_del = st.selectbox("Select Stock", opts)
            if st.button("Delete"): delete_portfolio_stock(s_del); st.rerun()


# ==============================================================================
#                                MAIN ROUTER
# ==============================================================================
if nav_option == "Dashboard":
    render_dashboard()
elif nav_option == "Live Trades":
    render_live()
elif nav_option == "Past Trades":
    render_past()
elif nav_option == "Portfolio Watch":
    render_portfolio()

time.sleep(1)
st.rerun()
