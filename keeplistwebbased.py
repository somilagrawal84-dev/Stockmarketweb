import streamlit as st
import pandas as pd
import os
from datetime import datetime

# --- Configuration ---
FILE_NAME = 'stocks.xlsx'
st.set_page_config(page_title="Team Stock Manager", layout="wide")


# --- Helper Functions ---
def load_data():
    """Loads data from Excel. Creates file if missing."""
    if not os.path.exists(FILE_NAME):
        # Create dummy data if file doesn't exist
        data = {
            'Stock Name': ['TCS', 'INFY'],
            'Date': [datetime.now().strftime('%Y-%m-%d')] * 2,
            'Stop Loss': [3000, 1400],
            'Target': [3500, 1600],
            'Actual Cost': [3200, 1350]
        }
        pd.DataFrame(data).to_excel(FILE_NAME, index=False)

    return pd.read_excel(FILE_NAME)


def save_data(df):
    """Saves dataframe to Excel."""
    df.to_excel(FILE_NAME, index=False)


# --- Main App Interface ---
st.title("📈 Shared Stock Portfolio Manager")

# 1. Load Data
df = load_data()

# 2. Sidebar - Add New Stock
with st.sidebar:
    st.header("➕ Add New Stock")
    with st.form("add_stock_form"):
        name = st.text_input("Stock Name")
        date = st.date_input("Date", value=datetime.now())
        sl = st.number_input("Stop Loss", value=0.0)
        target = st.number_input("Target", value=0.0)
        cost = st.number_input("Actual Cost", value=0.0)

        submitted = st.form_submit_button("Add Stock")

        if submitted:
            new_data = {
                'Stock Name': name,
                'Date': date.strftime('%Y-%m-%d'),
                'Stop Loss': sl,
                'Target': target,
                'Actual Cost': cost
            }
            # Append and Save
            df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
            save_data(df)
            st.success("Stock Added!")
            st.rerun()  # Refresh page to show new data

# 3. Main Area - Filter Logic
st.subheader("Market Watch")

col1, col2 = st.columns([1, 3])
with col1:
    # Filter Toggle
    filter_on = st.toggle("Filter: Show only if Cost is between SL and Target")

# Apply Filter
display_df = df.copy()


# Calculate Status for all rows
# (axis=1 applies the logic row by row)
def get_status(row):
    if row['Stop Loss'] <= row['Actual Cost'] <= row['Target']:
        return "In Range"
    return "Out of Range"


display_df['Status'] = display_df.apply(get_status, axis=1)

if filter_on:
    display_df = display_df[display_df['Status'] == "In Range"]

# 4. Display Table (Editable!)
# st.data_editor allows users to change values directly in the table
st.write("💡 *Tip: You can edit values directly in the table below.*")
edited_df = st.data_editor(
    display_df,
    num_rows="dynamic",  # Allows adding/deleting rows directly in UI
    use_container_width=True,
    key="data_editor"
)

# 5. Save Changes from Table Edits
# If the table content in UI is different from loaded DF, save it
# Note: We compare the edited version (edited_df) to the original (df)
# But since we might have filtered, we need to be careful.
# For simplicity in this web version, direct table editing updates the file immediately.

if not filter_on:
    # Only allow saving table edits if filter is OFF (to avoid losing hidden rows)
    if not edited_df.equals(df):
        save_data(edited_df)
        st.toast("Changes saved automatically!", icon="💾")
else:
    st.info("Turn off filter to edit data directly in the table.")

# 6. Delete Section (Alternative to table deletion)
with st.expander("🗑️ Delete Stock"):
    stock_to_delete = st.selectbox("Select Stock to Delete", df.index, format_func=lambda
        x: f"{df.loc[x, 'Stock Name']} (Cost: {df.loc[x, 'Actual Cost']})")
    if st.button("Delete Selected Stock"):
        df = df.drop(stock_to_delete).reset_index(drop=True)
        save_data(df)
        st.error("Stock Deleted.")
        st.rerun()