"""
defaulters.py — Owner-only defaulters report (one row per house)

Rule (updated as requested):
- Each house has exactly ONE defaulter record (owner is responsible).
- Even if house is on rent / multiple families, still ONE row only.

Dues:
- Dues are per HOUSE, based on monthly_charges for the selected scope (monthly/annual).

Payments:
- Payments are read from legacy bills and summed across the scope (monthly/annual).

Display columns (exactly as requested):
  1) House No (Owner)      e.g., "GT-1/23 (Owner)"
  2) Street No
  3) Owner’s Name
  4) Head’s Name           (owner)
  5) Head’s Phone No       (owner phone)
  6) Pending (Water / Security / Sanitation / Total)
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


# ─────────────────────── DB helpers ─────────────────────────────
def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


def ensure_schema() -> None:
    with closing(get_conn().cursor()) as cur:
        # Monthly charges per HOUSE
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_charges (
                billing_month   TEXT PRIMARY KEY,
                water_due       REAL NOT NULL DEFAULT 0,
                security_due    REAL NOT NULL DEFAULT 0,
                sanitation_due  REAL NOT NULL DEFAULT 0,
                updated_at      TEXT NOT NULL
            )
            """
        )

        # Legacy bills table (owner-only payments are stored here)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resident_id     INTEGER NOT NULL,
                billing_month   TEXT NOT NULL,
                water_bill      REAL DEFAULT 0,
                security_bill   REAL DEFAULT 0,
                sanitation_bill REAL DEFAULT 0,
                amount_paid     REAL DEFAULT 0,
                UNIQUE (resident_id, billing_month),
                FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute("PRAGMA table_info(bills)")
        cols = {c[1] for c in cur.fetchall()}
        if "amount_paid" not in cols:
            cur.execute("ALTER TABLE bills ADD COLUMN amount_paid REAL DEFAULT 0")

    get_conn().commit()


# ───────────────────────── Data loaders ─────────────────────────
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


def load_bills_for_month(yyyymm: str) -> pd.DataFrame:
    sql = """
        SELECT resident_id, water_bill, security_bill, sanitation_bill
        FROM bills
        WHERE billing_month = ?
    """
    df = pd.read_sql_query(sql, get_conn(), params=(yyyymm,))
    if df.empty:
        return pd.DataFrame(columns=["resident_id", "water_bill", "security_bill", "sanitation_bill"]).set_index("resident_id")
    return df.set_index("resident_id")


def load_monthly_charges(yyyymm: str) -> dict:
    row = get_conn().execute(
        "SELECT water_due, security_due, sanitation_due FROM monthly_charges WHERE billing_month = ?",
        (yyyymm,),
    ).fetchone()
    if not row:
        return {"water_due": 0.0, "security_due": 0.0, "sanitation_due": 0.0}
    return {"water_due": float(row[0]), "security_due": float(row[1]), "sanitation_due": float(row[2])}


# ─────────────────────────── Page ───────────────────────────────
def render() -> None:
    ensure_schema()
    st.header("🚨 Defaulters (Owner only — one row per house)")

    # 1 – scope
    scope = st.radio("Report scope", ("Monthly", "Annual"), horizontal=True)
    if scope == "Monthly":
        m_dt = st.date_input("Month", value=date.today().replace(day=1), format="YYYY/MM/DD")
        months = [m_dt.month]
        years = [m_dt.year]
        caption = f"{m_dt.strftime('%Y-%m')}"
    else:  # Annual
        yr = st.selectbox("Year", reversed(range(date.today().year - 5, date.today().year + 1)))
        months = list(range(1, 12 + 1))
        years = [yr]
        caption = str(yr)

    st.caption(f"Showing defaulters for **{caption}**")

    # 2 – service filter
    st.subheader("Include houses who owe for:")
    f_w = st.checkbox("Water", value=True)
    f_s = st.checkbox("Security", value=True)
    f_t = st.checkbox("Sanitation", value=True)
    if not (f_w or f_s or f_t):
        st.info("Select at least one service.")
        st.stop()

    # 3 – base frame: one row per house (owner only)
    residents = load_residents().copy()

    residents["unit_ref"] = residents["house_no"].astype(str) + " (Owner)"
    residents["head_name"] = residents["owner_name"]
    residents["head_phone"] = residents["owner_phone"]

    residents["water_paid"] = 0.0
    residents["security_paid"] = 0.0
    residents["sanitation_paid"] = 0.0

    # 3a – accumulate payments across scope (from bills)
    for y in years:
        for m in months:
            yyyymm = f"{y}-{m:02d}"
            b = load_bills_for_month(yyyymm)
            residents["water_paid"] += b["water_bill"].reindex(residents.index, fill_value=0)
            residents["security_paid"] += b["security_bill"].reindex(residents.index, fill_value=0)
            residents["sanitation_paid"] += b["sanitation_bill"].reindex(residents.index, fill_value=0)

    # 4 – compute total dues across scope (per HOUSE)
    total_water_due = total_security_due = total_sanitation_due = 0.0
    missing_months = []
    for y in years:
        for m in months:
            yyyymm = f"{y}-{m:02d}"
            charges = load_monthly_charges(yyyymm)
            if (charges["water_due"] + charges["security_due"] + charges["sanitation_due"]) == 0:
                missing_months.append(yyyymm)

            total_water_due += charges["water_due"]
            total_security_due += charges["security_due"]
            total_sanitation_due += charges["sanitation_due"]

    if missing_months:
        st.warning(
            "No monthly charges found for: " + ", ".join(missing_months) +
            ". These months were treated as 0 due. Set them in **Monthly Bill Entry** to include them."
        )

    # Apply facility eligibility flags per HOUSE
    residents["water_due"] = residents["facility_water"] * total_water_due
    residents["security_due"] = residents["facility_security"] * total_security_due
    residents["sanitation_due"] = residents["facility_sanitation"] * total_sanitation_due

    # Pending by service (never show negative pending)
    residents["water_pending"] = (residents["water_due"] - residents["water_paid"]).clip(lower=0)
    residents["security_pending"] = (residents["security_due"] - residents["security_paid"]).clip(lower=0)
    residents["sanitation_pending"] = (residents["sanitation_due"] - residents["sanitation_paid"]).clip(lower=0)

    # 5 – filter defaulters by selected services
    mask = False
    if f_w:
        mask |= residents["water_pending"] > 0
    if f_s:
        mask |= residents["security_pending"] > 0
    if f_t:
        mask |= residents["sanitation_pending"] > 0

    defaulters = residents[mask].copy()
    if defaulters.empty:
        st.success("🎉 No defaulters!")
        st.stop()

    defaulters["Total pending"] = (
        defaulters["water_pending"] +
        defaulters["security_pending"] +
        defaulters["sanitation_pending"]
    )

    # 6 – display (exact requested columns)
    view = defaulters.reset_index()
    view.insert(0, "S.No", range(1, len(view) + 1))

    cols = [
        "S.No",
        "unit_ref",      # House No
        "street_name",   # Street
        "owner_name",    # Owner’s Name
        "head_name",     # Head’s Name (owner)
        "head_phone",    # Head’s Phone (owner)
        "water_pending", "security_pending", "sanitation_pending", "Total pending",
    ]

    cfg = {
        "S.No": st.column_config.NumberColumn("S.No", disabled=True, format="%.0f"),
        "unit_ref": st.column_config.TextColumn("House", disabled=True),
        "street_name": st.column_config.TextColumn("Street", disabled=True),
        "owner_name": st.column_config.TextColumn("Owner", disabled=True),
        "head_name": st.column_config.TextColumn("Head", disabled=True),
        "head_phone": st.column_config.TextColumn("Head Phone", disabled=True),
        "water_pending": st.column_config.NumberColumn("Water", disabled=True, format="%.0f"),
        "security_pending": st.column_config.NumberColumn("Security", disabled=True, format="%.0f"),
        "sanitation_pending": st.column_config.NumberColumn("Sanitation", disabled=True, format="%.0f"),
        "Total pending": st.column_config.NumberColumn("Total", disabled=True, format="%.0f"),
    }

    st.subheader("Defaulters list (Owner only)")
    st.data_editor(
        view[cols],
        column_config=cfg,
        hide_index=True,
        disabled=cols,
        use_container_width=True,
    )

    csv = view[cols].to_csv(index=False).encode()
    st.download_button("Download CSV", csv, file_name="defaulters_owner_only.csv", mime="text/csv")


if __name__ == "__main__":
    render()
