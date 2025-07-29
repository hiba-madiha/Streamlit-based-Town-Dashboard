"""
Ghouri Town Dashboard · Fund Management Page
────────────────────────────────────────────
Features
• List existing funds OR create a new one.
• View a tabular overview (title, month, contributors, total).
• Add / update / remove individual resident contributions at any time.
• Delete an entire fund with two‑step confirmation.
(No charts – text/table view only.)
"""
from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

# ──────────────────────────────────────────────────────────────────────
# 1. Database helpers
# ──────────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "residents.db"


def get_conn() -> sqlite3.Connection:
    """Return a singleton SQLite connection with FK cascades ON."""
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


# ──────────────────────────────────────────────────────────────────────
# 2. Schema (runs once if tables are missing)
# ──────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS funds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_title  TEXT NOT NULL,
    fund_month  TEXT NOT NULL,                -- YYYY-MM
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (fund_title, fund_month)
);

CREATE TABLE IF NOT EXISTS contributions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id       INTEGER NOT NULL,
    resident_id   INTEGER NOT NULL,
    amount        REAL    NOT NULL,
    FOREIGN KEY (fund_id)     REFERENCES funds(id)     ON DELETE CASCADE,
    FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE,
    UNIQUE (fund_id, resident_id)
);
"""
with get_conn() as _c:
    _c.executescript(SCHEMA_SQL)

# ──────────────────────────────────────────────────────────────────────
# 3. Data loaders
# ──────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_residents() -> pd.DataFrame:
    q = """
        SELECT id AS resident_id,
               house_no, street_name,
               owner_name, owner_phone
          FROM residents
    """
    df = pd.read_sql_query(q, get_conn())
    return df.set_index("resident_id")


@st.cache_data(show_spinner=False)
def load_funds() -> pd.DataFrame:
    q = """
        SELECT f.id,
               f.fund_title,
               f.fund_month,
               COALESCE(SUM(c.amount), 0)                           AS total_amt,
               SUM(CASE WHEN c.amount > 0 THEN 1 ELSE 0 END)       AS n_contrib
          FROM funds              AS f
     LEFT JOIN contributions AS c ON f.id = c.fund_id
      GROUP BY f.id
      ORDER BY f.fund_month DESC, f.fund_title
    """
    return pd.read_sql_query(q, get_conn())


def get_or_create_fund(title: str, month: str) -> int:
    """Return fund_id – creates new record if needed (idempotent)."""
    conn = get_conn()
    cur = conn.execute(
        "SELECT id FROM funds WHERE fund_title = ? AND fund_month = ?",
        (title, month),
    )
    found = cur.fetchone()
    if found:
        return found[0]

    cur = conn.execute(
        "INSERT INTO funds (fund_title, fund_month) VALUES (?, ?)",
        (title, month),
    )
    conn.commit()
    return cur.lastrowid


def load_contributions(fund_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT resident_id, amount FROM contributions WHERE fund_id = ?",
        get_conn(),
        params=(fund_id,),
    )
    if df.empty:
        return pd.DataFrame(columns=["resident_id", "amount"]).set_index("resident_id")
    return df.set_index("resident_id")

# ──────────────────────────────────────────────────────────────────────
# 4. Page
# ──────────────────────────────────────────────────────────────────────

def render() -> None:
    st.header("💰 Fund Management")

    # 4‑A  Fund selector / creator ------------------------------------
    funds_df = load_funds()
    selector_opts = ["➕ New fund"] + [
        f"{row.fund_title} — {row.fund_month}" for _, row in funds_df.iterrows()
    ]
    choice = st.selectbox("Select a fund", selector_opts, index=0)

    new_mode = choice.startswith("➕")
    title_col, month_col = st.columns(2)

    if new_mode:
        fund_title = title_col.text_input("Fund title *", placeholder="e.g. Eid Decorations")
        default_month = date.today().replace(day=1)
        fund_month = month_col.date_input(
            "Fund month *", default_month, format="YYYY/MM/DD"
        )
        fund_month_str = fund_month.strftime("%Y-%m")

        if not fund_title:
            st.info("Enter title & month, then press **Create fund**.")
            st.stop()

        if st.button("Create fund", type="primary"):
            new_id = get_or_create_fund(fund_title.strip(), fund_month_str)
            st.session_state["active_fund_id"] = new_id
            st.success("Fund created / opened.")
            st.cache_data.clear()
            st.rerun()
        st.stop()

    # 4‑B  Existing fund selected -------------------------------------
    active_row  = funds_df.iloc[selector_opts.index(choice) - 1]
    fund_id     = int(active_row.id)
    fund_title  = active_row.fund_title
    fund_month_str = active_row.fund_month
    st.caption(f"Editing **{fund_title} — {fund_month_str}**  (ID {fund_id})")

    # 4‑C  Delete workflow (two‑step) ----------------------------------
    del_btn = st.button("🗑 Delete this fund", key=f"del_{fund_id}")
    if del_btn:
        st.session_state["delete_target_id"] = fund_id

    if st.session_state.get("delete_target_id") == fund_id:
        st.error("⚠️ This will permanently remove the fund **and** all its contributions.")
        confirm_col, cancel_col = st.columns(2)

        if confirm_col.button("✅ Yes, delete", key=f"conf_{fund_id}"):
            try:
                conn = get_conn()
                conn.execute("DELETE FROM funds WHERE id = ?", (fund_id,))
                conn.commit()
                st.success("Fund deleted.")
                st.session_state.pop("delete_target_id", None)
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"DB error: {exc}")

        if cancel_col.button("❌ Cancel", key=f"cancel_{fund_id}"):
            st.session_state.pop("delete_target_id", None)
            st.info("Delete cancelled.")

    # 4‑D  Overview table (text‑only) ----------------------------------
    with st.expander("📋 Fund overview", expanded=False):
        st.dataframe(
            funds_df.rename(
                columns={
                    "fund_title": "Title",
                    "fund_month": "Month",
                    "total_amt": "Total Rs",
                    "n_contrib": "Contributors",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    # 4‑E  Contributions editor (fixed) --------------------------------
    residents  = load_residents().reset_index()               # keep id visible for code
    contribs   = load_contributions(fund_id).reset_index()

    editable = residents.merge(contribs, on="resident_id", how="left")
    editable["Amount"] = editable["amount"].astype(float)         # float dtype; NaN shows blank
    editable.drop(columns=["amount"], inplace=True)
    editable["Contributed?"] = ~editable["Amount"].isna()

    st.markdown("### Enter / update contributions")
    edited = st.data_editor(
        editable,
        column_config={
            "Contributed?": st.column_config.CheckboxColumn(width="small"),
            "Amount":       st.column_config.NumberColumn(step=100.0, min_value=0.0),
        },
        disabled=["resident_id", "house_no", "street_name", "owner_name", "owner_phone"],
        hide_index=True,
        use_container_width=True,
        key="contrib_editor",
    )

    # 4‑F  Persist changes (fixed) ------------------------------------
    if st.button("💾 Save contributions", type="primary"):
        to_upsert, to_delete, errs = [], [], []

        for _, row in edited.iterrows():
            rid      = int(row["resident_id"])
            ticked   = bool(row["Contributed?"])
            amt_cell = row["Amount"]

            if ticked and (pd.isna(amt_cell) or float(amt_cell) <= 0):
                errs.append(f"House {row.house_no}: amount required if ticked.")
                continue
            if not ticked:
                to_delete.append(rid)
            else:
                to_upsert.append((fund_id, rid, float(amt_cell)))

        if errs:
            st.error("⚠️ " + "  \n".join(errs))
            st.stop()

        conn = get_conn()
        try:
            with conn:                                  # atomic transaction
                if to_upsert:
                    conn.executemany(
                        """
                        INSERT INTO contributions (fund_id, resident_id, amount)
                             VALUES (?, ?, ?)
                        ON CONFLICT(fund_id, resident_id)
                        DO UPDATE SET amount = excluded.amount
                        """,
                        to_upsert,
                    )
                if to_delete:
                    conn.executemany(
                        "DELETE FROM contributions WHERE fund_id = ? AND resident_id = ?",
                        [(fund_id, rid) for rid in to_delete],
                    )
            st.success("Saved!")
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"DB error: {exc}")


# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    render()
