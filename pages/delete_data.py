import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import streamlit as st

# ────────────────────────────────────────────────────────────────────────────────
# DB helpers (shared with other pages)
# ────────────────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "residents.db"


def get_connection():
    """Return a singleton SQLite connection with FK cascades on."""
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")  # ensure ON DELETE CASCADE
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


@st.cache_data(show_spinner=False)
def load_residents_df():
    """Read the residents table into a DataFrame."""
    q = """
    SELECT id, house_no, street_name,
           owner_name, owner_cnic, owner_phone,
           is_rent, lessee_name, lessee_cnic, lessee_phone,
           floors,
           facility_water, facility_security, facility_sanitation
      FROM residents
     ORDER BY id DESC
    """
    df = pd.read_sql_query(q, get_connection())
    bool_cols = [
        "is_rent",
        "facility_water",
        "facility_security",
        "facility_sanitation",
    ]
    df[bool_cols] = df[bool_cols].astype(bool)
    return df


def delete_residents(ids: list[int]):
    """DELETE rows from residents (families will cascade)."""
    if not ids:
        return
    conn = get_connection()
    with closing(conn.cursor()) as cur:
        cur.executemany("DELETE FROM residents WHERE id = ?", [(rid,) for rid in ids])
        conn.commit()


# ────────────────────────────────────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────────────────────────────────────

def render():
    st.header("🗑️ Delete Resident Data")

    df = load_residents_df()
    df.insert(0, "Select", False)  # checkbox column comes first

    # Only the Select column is editable
    disabled_cols = [c for c in df.columns if c != "Select"]

    edited_df = st.data_editor(
        df,
        key="deleter_table",
        num_rows="fixed",
        use_container_width=True,
        disabled=disabled_cols,
        column_config={
            "Select": st.column_config.CheckboxColumn(label="Delete?", width="small"),
        },
    )

    selected_ids = edited_df[edited_df["Select"]]["id"].tolist()

    if not selected_ids:
        st.info("Tick the **Delete?** checkbox in one or more rows to mark them for deletion.")
        return

    st.warning(f"You have selected **{len(selected_ids)}** record(s). This will permanently remove the house and all its family data.")

    if st.button(f"🗑️ Delete selected ({len(selected_ids)})", type="primary", key="delete_btn"):
        delete_residents(selected_ids)
        st.success("Deleted!")
        st.cache_data.clear()  # refresh the cached dataframe
        st.rerun()


'''if __name__ == "__main__":
    render()'''
