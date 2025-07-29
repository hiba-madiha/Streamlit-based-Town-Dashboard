"""
defaulters.py — List residents who missed or under-paid at least ONE bill
in the selected month or in ANY month of the selected year.
"""

from __future__ import annotations
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# ─────────────────────────── Globals ────────────────────────────
DB_PATH = Path(__file__).parent.parent / "residents.db"
DEFAULT_WATER_DUE      = 500
DEFAULT_SECURITY_DUE   = 500
DEFAULT_SANITATION_DUE = 1_000


# ─────────────────────── DB helpers ─────────────────────────────
def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


def load_residents() -> pd.DataFrame:
    sql = """
        SELECT id AS resident_id,
               house_no, street_name, owner_name, owner_phone,
               facility_water, facility_security, facility_sanitation
        FROM residents ORDER BY street_name, house_no
    """
    return pd.read_sql_query(sql, get_conn()).set_index("resident_id")


def load_paid_for_month(yyyymm: str) -> pd.DataFrame:
    sql = """
        SELECT resident_id, water_bill, security_bill, sanitation_bill
        FROM bills WHERE billing_month = ?
    """
    return pd.read_sql_query(sql, get_conn(), params=(yyyymm,)).set_index("resident_id")


# ─────────────────────────── Page ───────────────────────────────
def render() -> None:
    st.header("🚨 Defaulters")

    # 1 – scope
    scope = st.radio("Report scope", ("Monthly", "Annual"), horizontal=True)
    if scope == "Monthly":
        m_dt = st.date_input("Month", value=date.today().replace(day=1), format="YYYY/MM/DD")
        months = [m_dt.month]
        years  = [m_dt.year]
        caption = f"{m_dt.strftime('%Y-%m')}"
    else:  # Annual
        yr = st.selectbox("Year", reversed(range(date.today().year - 5, date.today().year + 1)))
        months = list(range(1, 13))
        years  = [yr]
        caption = str(yr)

    st.caption(f"Showing defaulters for **{caption}**")

    # 2 – expected dues
    st.subheader("Expected monthly charge per service")
    c1, c2, c3 = st.columns(3)
    due_w = c1.number_input("Water (Rs)",      0, value=int(DEFAULT_WATER_DUE),      step=100)
    due_s = c2.number_input("Security (Rs)",   0, value=int(DEFAULT_SECURITY_DUE),   step=100)
    due_t = c3.number_input("Sanitation (Rs)", 0, value=int(DEFAULT_SANITATION_DUE), step=100)

    # 3 – service filter
    st.subheader("Include residents who owe for:")
    f_w = st.checkbox("Water",      value=True)
    f_s = st.checkbox("Security",   value=True)
    f_t = st.checkbox("Sanitation", value=True)
    if not (f_w or f_s or f_t):
        st.info("Select at least one service.")
        st.stop()

    # 4 – prepare dataframe
    df = load_residents()
    for col in ["water_paid", "security_paid", "sanitation_paid"]:
        df[col] = 0.0

    # 4a – accumulate payments (PATCHED)
    for y in years:
        for m in months:
            yyyymm = f"{y}-{m:02d}"
            paid = load_paid_for_month(yyyymm)
            for svc, col in [
                ("water_bill",      "water_paid"),
                ("security_bill",   "security_paid"),
                ("sanitation_bill", "sanitation_paid"),
            ]:
                df[col] += paid[svc].reindex(df.index, fill_value=0)   # ← fixed

    m_cnt = len(months)  # 1 for monthly, 12 for annual

    # 5 – compute due & pending
    df["water_due"]      = df["facility_water"]      * due_w * m_cnt
    df["security_due"]   = df["facility_security"]   * due_s * m_cnt
    df["sanitation_due"] = df["facility_sanitation"] * due_t * m_cnt

    df["water_pending"]      = df["water_due"]      - df["water_paid"]
    df["security_pending"]   = df["security_due"]   - df["security_paid"]
    df["sanitation_pending"] = df["sanitation_due"] - df["sanitation_paid"]

    # 6 – filter defaulters
    mask = False
    if f_w: mask |= df["water_pending"]      > 0
    if f_s: mask |= df["security_pending"]   > 0
    if f_t: mask |= df["sanitation_pending"] > 0
    defaulters = df[mask].copy()

    if defaulters.empty:
        st.success("🎉 No defaulters!")
        st.stop()

    defaulters["Total pending"] = (
        defaulters["water_pending"]
        + defaulters["security_pending"]
        + defaulters["sanitation_pending"]
    )

    defaulters = defaulters.reset_index()
    defaulters.insert(0, "S.No", range(1, len(defaulters) + 1))

    # 7 – display
    cols = [
        "S.No", "house_no", "street_name", "owner_name", "owner_phone",
        "water_pending", "security_pending", "sanitation_pending", "Total pending",
    ]
    cfg = {
        "S.No": st.column_config.NumberColumn("S.No", disabled=True, format="%.0f"),
        "house_no":    st.column_config.TextColumn("House #", disabled=True),
        "street_name": st.column_config.TextColumn("Street",  disabled=True),
        "owner_name":  st.column_config.TextColumn("Owner",   disabled=True),
        "owner_phone": st.column_config.TextColumn("Phone",   disabled=True),
        "water_pending":      st.column_config.NumberColumn("Water",      disabled=True, format="%.0f"),
        "security_pending":   st.column_config.NumberColumn("Security",   disabled=True, format="%.0f"),
        "sanitation_pending": st.column_config.NumberColumn("Sanitation", disabled=True, format="%.0f"),
        "Total pending":      st.column_config.NumberColumn("Total",      disabled=True, format="%.0f"),
    }

    st.subheader("Defaulters list")
    st.data_editor(
        defaulters[cols],
        column_config=cfg,
        hide_index=True,
        disabled=cols,
        use_container_width=True,
    )

    csv = defaulters[cols].to_csv(index=False).encode()
    st.download_button("Download CSV", csv, file_name="defaulters.csv", mime="text/csv")


if __name__ == "__main__":
    render()
