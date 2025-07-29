"""
bill_entry.py — 9-column Monthly Bill & Payments sheet
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

# ───────────────────────────── Globals ─────────────────────────────
DB_PATH = Path(__file__).parent.parent / "residents.db"
DEFAULT_WATER_DUE      = 500
DEFAULT_SECURITY_DUE   = 500
DEFAULT_SANITATION_DUE = 1_000


# ─────────────────────────── DB helpers ────────────────────────────
def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


with closing(get_conn().cursor()) as cur:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resident_id     INTEGER NOT NULL,
            billing_month   TEXT NOT NULL,
            water_bill      REAL DEFAULT 0,  -- amounts PAID
            security_bill   REAL DEFAULT 0,
            sanitation_bill REAL DEFAULT 0,
            amount_paid     REAL DEFAULT 0,
            UNIQUE (resident_id, billing_month),
            FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
        )
        """
    )
    # add amount_paid if upgrading from older schema
    cur.execute("PRAGMA table_info(bills)")
    if "amount_paid" not in {info[1] for info in cur.fetchall()}:
        cur.execute("ALTER TABLE bills ADD COLUMN amount_paid REAL DEFAULT 0")
    get_conn().commit()


# ────────────────────────── Data helpers ───────────────────────────
def load_residents() -> pd.DataFrame:
    sql = """
        SELECT id AS resident_id,
               house_no, street_name,
               owner_name, owner_phone,
               facility_water, facility_security, facility_sanitation
        FROM residents
        ORDER BY street_name, house_no
    """
    return pd.read_sql_query(sql, get_conn()).set_index("resident_id")


def load_paid(month: str) -> pd.DataFrame:
    sql = """
        SELECT resident_id, water_bill, security_bill, sanitation_bill
        FROM bills WHERE billing_month = ?
    """
    return pd.read_sql_query(sql, get_conn(), params=(month,)).set_index("resident_id")


def save_rows(df: pd.DataFrame, month: str) -> None:
    conn = get_conn()
    with closing(conn.cursor()) as cur, conn:
        for rid, row in df.iterrows():
            total = float(row.water_bill) + float(row.security_bill) + float(row.sanitation_bill)
            cur.execute(
                """
                INSERT INTO bills (
                    resident_id, billing_month,
                    water_bill, security_bill, sanitation_bill,
                    amount_paid
                ) VALUES (?,?,?,?,?,?)
                ON CONFLICT(resident_id, billing_month) DO UPDATE SET
                    water_bill      = excluded.water_bill,
                    security_bill   = excluded.security_bill,
                    sanitation_bill = excluded.sanitation_bill,
                    amount_paid     = excluded.amount_paid
                """,
                (
                    int(rid), month,
                    float(row.water_bill or 0),
                    float(row.security_bill or 0),
                    float(row.sanitation_bill or 0),
                    total,
                ),
            )


# ──────────────────────────── Page UI ─────────────────────────────
def render() -> None:
    st.header("💵 Monthly Bill Entry")

    # ── 1. Choose month ─────────────────────────────────────────────
    first_of_month = date.today().replace(day=1)
    mdate = st.date_input("Billing month", first_of_month, format="YYYY/MM/DD")
    month = mdate.strftime("%Y-%m")
    st.caption(f"Recording payments for **{month}**")

    # ── 2. Defaults (all int arguments → avoids MixedNumericTypesError) ──
    st.subheader("Default charges (per house)")
    c1, c2, c3 = st.columns(3)
    due_water = c1.number_input("Water due",      min_value=0, value=int(DEFAULT_WATER_DUE),      step=100)
    due_sec   = c2.number_input("Security due",   min_value=0, value=int(DEFAULT_SECURITY_DUE),   step=100)
    due_san   = c3.number_input("Sanitation due", min_value=0, value=int(DEFAULT_SANITATION_DUE), step=100)

    # ── 3. Load data ────────────────────────────────────────────────
    res  = load_residents()
    paid = load_paid(month)
    for col in ["water_bill", "security_bill", "sanitation_bill"]:
        res[col] = paid[col].fillna(0)

    # Dues per house (hidden)
    res["_water_due"]      = res["facility_water"]      * due_water
    res["_security_due"]   = res["facility_security"]   * due_sec
    res["_sanitation_due"] = res["facility_sanitation"] * due_san

    # Pending
    res["pending"] = (
        res[["_water_due", "_security_due", "_sanitation_due"]].sum(axis=1)
        - res[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
    )

    # Serial numbers
    res = res.reset_index()
    res.insert(0, "S.No", range(1, len(res) + 1))

    # ── 4. Column configuration ─────────────────────────────────────
    cfg = {
        "S.No":           st.column_config.NumberColumn("S.No", disabled=True, format="%.0f"),
        "house_no":       st.column_config.TextColumn("House #", disabled=True),
        "street_name":    st.column_config.TextColumn("Street",  disabled=True),
        "owner_name":     st.column_config.TextColumn("Owner",   disabled=True),
        "owner_phone":    st.column_config.TextColumn("Phone",   disabled=True),

        # paid amounts — always editable
        "water_bill":      st.column_config.NumberColumn("Water paid",      step=100, format="%.0f"),
        "security_bill":   st.column_config.NumberColumn("Security paid",   step=100, format="%.0f"),
        "sanitation_bill": st.column_config.NumberColumn("Sanitation paid", step=100, format="%.0f"),

        "pending": st.column_config.NumberColumn("Pending", disabled=True, format="%.0f"),
    }

    display = [
        "S.No", "house_no", "street_name", "owner_name", "owner_phone",
        "water_bill", "security_bill", "sanitation_bill", "pending",
    ]

    sheet = st.data_editor(
        res[display],
        column_config=cfg,
        hide_index=True,
        key="bill_editor",
        use_container_width=True,
    )

    # Live pending
    sheet["pending"] = (
        res[["_water_due", "_security_due", "_sanitation_due"]].sum(axis=1)
        - sheet[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
    )

    # ── 5. Save all rows ────────────────────────────────────────────
    if st.button("💾 Save records", type="primary"):
        rows = sheet.copy()
        rows["resident_id"] = res["resident_id"]  # restore idx lost after reset_index()
        save_rows(rows.set_index("resident_id")[["water_bill", "security_bill", "sanitation_bill"]], month)
        st.success("✅ Records saved!")
        st.rerun()


if __name__ == "__main__":
    render()
