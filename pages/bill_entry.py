"""
bill_entry.py — Monthly Bill & Payments (OWNER ONLY)

Rule (updated as requested):
- Each house has exactly ONE bill entry per month (owner pays everything).
- Even if house is on rent / multiple families, still ONE row only.

Display columns (exactly as requested):
  1) House No (Owner)      e.g., "GT-1/23 (Owner)"
  2) Street No
  3) Owner’s Name
  4) Head’s Name           (owner)
  5) Head’s Phone No       (owner)
  6) Bill (Water / Security / Sanitation)

Storage:
- Payments are stored in legacy `bills` keyed by (resident_id, billing_month)
- Monthly due amounts stored in `monthly_charges` keyed by billing_month
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ───────────────────────────── Globals ─────────────────────────────
DB_PATH = Path(__file__).parent.parent / "residents.db"
DEFAULT_WATER_DUE = 500
DEFAULT_SECURITY_DUE = 500
DEFAULT_SANITATION_DUE = 1000


# ─────────────────────────── DB helpers ────────────────────────────
def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


def ensure_schema() -> None:
    """Create/upgrade tables needed for owner-only billing & payments."""
    conn = get_conn()
    with closing(conn.cursor()) as cur:
        # Legacy summary table (used by defaulters and reports)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resident_id     INTEGER NOT NULL,
                billing_month   TEXT NOT NULL,         -- 'YYYY-MM'
                water_bill      REAL DEFAULT 0,        -- amounts PAID
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

        # Monthly charges (per HOUSE)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_charges (
                billing_month   TEXT PRIMARY KEY,      -- 'YYYY-MM'
                water_due       REAL NOT NULL DEFAULT 0,
                security_due    REAL NOT NULL DEFAULT 0,
                sanitation_due  REAL NOT NULL DEFAULT 0,
                updated_at      TEXT NOT NULL          -- ISO datetime
            )
            """
        )
    conn.commit()


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


def load_bills(month: str) -> pd.DataFrame:
    sql = """
        SELECT resident_id, water_bill, security_bill, sanitation_bill, amount_paid
        FROM bills
        WHERE billing_month = ?
    """
    df = pd.read_sql_query(sql, get_conn(), params=(month,))
    if df.empty:
        return pd.DataFrame(
            columns=["resident_id", "water_bill", "security_bill", "sanitation_bill", "amount_paid"]
        ).set_index("resident_id")
    return df.set_index("resident_id")


def load_monthly_charges(month: str) -> dict:
    row = get_conn().execute(
        "SELECT water_due, security_due, sanitation_due FROM monthly_charges WHERE billing_month = ?",
        (month,),
    ).fetchone()
    if not row:
        return {"water_due": None, "security_due": None, "sanitation_due": None}
    return {"water_due": row[0], "security_due": row[1], "sanitation_due": row[2]}


def save_monthly_charges(month: str, water: float, security: float, sanitation: float) -> None:
    get_conn().execute(
        """
        INSERT INTO monthly_charges (billing_month, water_due, security_due, sanitation_due, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(billing_month) DO UPDATE SET
            water_due      = excluded.water_due,
            security_due   = excluded.security_due,
            sanitation_due = excluded.sanitation_due,
            updated_at     = excluded.updated_at
        """,
        (month, float(water), float(security), float(sanitation), datetime.utcnow().isoformat(timespec="seconds")),
    )
    get_conn().commit()


def upsert_bills_owner_only(df_owner: pd.DataFrame, month: str) -> None:
    """
    df_owner index = resident_id
    columns: water_bill, security_bill, sanitation_bill
    """
    conn = get_conn()
    with closing(conn.cursor()) as cur, conn:
        for rid, row in df_owner.iterrows():
            w = float(row.get("water_bill", 0) or 0)
            s = float(row.get("security_bill", 0) or 0)
            t = float(row.get("sanitation_bill", 0) or 0)
            total = w + s + t

            cur.execute(
                """
                INSERT INTO bills (resident_id, billing_month, water_bill, security_bill, sanitation_bill, amount_paid)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(resident_id, billing_month) DO UPDATE SET
                    water_bill      = excluded.water_bill,
                    security_bill   = excluded.security_bill,
                    sanitation_bill = excluded.sanitation_bill,
                    amount_paid     = excluded.amount_paid
                """,
                (int(rid), month, w, s, t, total),
            )


# ──────────────────────────── Page UI ─────────────────────────────
def render() -> None:
    ensure_schema()
    st.header("💵 Monthly Bill Entry (Owner only)")

    # 1) Choose month
    first_of_month = date.today().replace(day=1)
    mdate = st.date_input("Billing month", first_of_month, format="YYYY/MM/DD")
    month = mdate.strftime("%Y-%m")
    st.caption(f"Recording payments for **{month}** (one row per house, owner pays)")

    # 2) Monthly charges (persisted per HOUSE)
    st.subheader("Monthly charges (per house) — saved for the selected month")
    existing = load_monthly_charges(month)
    c1, c2, c3 = st.columns(3)
    due_water = c1.number_input(
        "Water due", min_value=0,
        value=int(existing["water_due"] or DEFAULT_WATER_DUE),
        step=100, key="due_water"
    )
    due_sec = c2.number_input(
        "Security due", min_value=0,
        value=int(existing["security_due"] or DEFAULT_SECURITY_DUE),
        step=100, key="due_sec"
    )
    due_san = c3.number_input(
        "Sanitation due", min_value=0,
        value=int(existing["sanitation_due"] or DEFAULT_SANITATION_DUE),
        step=100, key="due_san"
    )

    if st.button("💾 Save monthly charges"):
        save_monthly_charges(month, due_water, due_sec, due_san)
        st.success("Charges saved.")

    # 3) Load residents + existing bills for month
    residents = load_residents()
    bills = load_bills(month)

    # 4) Build OWNER-ONLY sheet (one row per resident/house)
    df = residents.reset_index().copy()
    df["unit_ref"] = df["house_no"].astype(str) + " (Owner)"
    df["head_name"] = df["owner_name"]
    df["head_phone"] = df["owner_phone"]

    # Attach existing paid values (if any)
    df = df.merge(
        bills.reset_index()[["resident_id", "water_bill", "security_bill", "sanitation_bill"]],
        on="resident_id", how="left",
    )
    df["water_bill"] = df["water_bill"].fillna(0)
    df["security_bill"] = df["security_bill"].fillna(0)
    df["sanitation_bill"] = df["sanitation_bill"].fillna(0)

    # 5) Editors (eligible houses only per service, based on house facilities)
    st.subheader("Enter payments (owner only, one row per house)")
    tabs = st.tabs(["💧 Water", "🛡️ Security", "🧹 Sanitation"])

    def edit_for_service(service: str, flag_col: str, value_col: str, key_suffix: str):
        dfx = df.copy()
        dfx = dfx[dfx[flag_col] == 1].copy()

        # Keep identity stable even if table sorts
        dfx["RID"] = dfx["resident_id"].astype(int).astype(str)

        display_cols = [
            "unit_ref",        # 1) House No
            "street_name",     # 2) Street No
            "owner_name",      # 3) Owner’s Name
            "head_name",       # 4) Head’s Name (owner)
            "head_phone",      # 5) Head’s Phone No
            value_col,         # 6) Bill for the service
            "RID",             # mapping key (disabled)
        ]

        cfg = {
            "unit_ref":    st.column_config.TextColumn("House", disabled=True),
            "street_name": st.column_config.TextColumn("Street", disabled=True),
            "owner_name":  st.column_config.TextColumn("Owner", disabled=True),
            "head_name":   st.column_config.TextColumn("Head", disabled=True),
            "head_phone":  st.column_config.TextColumn("Head Phone", disabled=True),
            value_col:     st.column_config.NumberColumn(f"{service} paid", step=100, format="%.0f"),
            "RID":         st.column_config.TextColumn("RID", disabled=True, width="small"),
        }

        edited = st.data_editor(
            dfx[display_cols],
            column_config=cfg,
            hide_index=True,
            key=f"editor_{key_suffix}",
            use_container_width=True,
        )

        # Map edits back using RID
        for _, r in edited.iterrows():
            rid = int(r["RID"])
            df.loc[df["resident_id"] == rid, value_col] = float(r[value_col] or 0)

    with tabs[0]:
        edit_for_service("Water", "facility_water", "water_bill", "water")
    with tabs[1]:
        edit_for_service("Security", "facility_security", "security_bill", "security")
    with tabs[2]:
        edit_for_service("Sanitation", "facility_sanitation", "sanitation_bill", "sanitation")

    # 6) Compute pending (per HOUSE)
    df["_water_due"] = df["facility_water"] * (existing["water_due"] if existing["water_due"] is not None else 0)
    df["_security_due"] = df["facility_security"] * (existing["security_due"] if existing["security_due"] is not None else 0)
    df["_sanitation_due"] = df["facility_sanitation"] * (existing["sanitation_due"] if existing["sanitation_due"] is not None else 0)

    df["pending"] = (
        df[["_water_due", "_security_due", "_sanitation_due"]].sum(axis=1)
        - df[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
    )

    # 7) Preview (read-only) with required columns + totals
    prev = df.copy()
    prev.insert(0, "S.No", range(1, len(prev) + 1))
    show_cols = [
        "S.No",
        "unit_ref", "street_name", "owner_name", "head_name", "head_phone",
        "water_bill", "security_bill", "sanitation_bill", "pending"
    ]
    st.subheader("Summary (per house / owner)")
    st.data_editor(
        prev[show_cols],
        hide_index=True,
        disabled=show_cols,
        use_container_width=True,
    )

    # 8) Save payments into legacy bills table
    if st.button("💾 Save payment records", type="primary"):
        # Zero out payments for ineligible facilities
        df.loc[df["facility_water"] == 0, "water_bill"] = 0
        df.loc[df["facility_security"] == 0, "security_bill"] = 0
        df.loc[df["facility_sanitation"] == 0, "sanitation_bill"] = 0

        # Persist monthly charges
        save_monthly_charges(month, due_water, due_sec, due_san)

        # Persist bills (owner only)
        to_save = df.set_index("resident_id")[["water_bill", "security_bill", "sanitation_bill"]].copy()
        upsert_bills_owner_only(to_save, month)

        st.success("✅ Owner-only payments saved (one row per house)!")
        st.rerun()


if __name__ == "__main__":
    render()
