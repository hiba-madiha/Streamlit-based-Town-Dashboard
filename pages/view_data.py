"""
Ghouri Town Dashboard · View Data  v4.0
───────────────────────────────────────────────────────────────────────
• NEW **Town Overview** tab → shows global counts (streets, houses, residents),
  houses‑per‑street table, monthly bill collection stats, per‑street recovery,
  and fund participation.
• Added **🔄 Refresh data** button (sidebar) + 5‑min cache TTL so any DB edits
  propagate quickly without restarting Streamlit.
• Existing Resident Summary, KPIs, tables, trends, aging, coverage, outstanding
  remain unchanged.
"""

from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
import sqlite3

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

# ────────────────────────────────────────────────────────────
# 1. DB helpers
# ────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "residents.db"
STREETS = [
    "Al-Rehman Road",
    "Ali Road",
    "Habib Road",
    "Bilal Road",
    "Khadija Road",
] + [f"Street {i}" for i in range(1, 23)]


def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = c
    return st.session_state["_db_conn"]


def table_exists(name: str) -> bool:
    return bool(
        get_conn()
        .execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (name,),
        )
        .fetchone()
    )


# ────────────────────────────────────────────────────────────
# 2. Cached data loaders  (auto‑refresh every 5 min)
# ────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_residents() -> pd.DataFrame:
    if not table_exists("residents"):
        return pd.DataFrame()
    sql = """
        SELECT id AS resident_id,
               house_no, street_name,
               owner_name, owner_phone,
               COALESCE(is_rent,0)             AS is_rent,
               COALESCE(facility_water,0)      AS facility_water,
               COALESCE(facility_security,0)   AS facility_security,
               COALESCE(facility_sanitation,0) AS facility_sanitation,
               COALESCE(created_at,'')         AS created_at
          FROM residents
    """
    df = pd.read_sql_query(sql, get_conn())
    bool_cols = [
        "is_rent",
        "facility_water",
        "facility_security",
        "facility_sanitation",
    ]
    df[bool_cols] = df[bool_cols].astype(bool)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_families() -> pd.DataFrame:
    if not table_exists("families"):
        return pd.DataFrame()
    cols = [c[1] for c in get_conn().execute("PRAGMA table_info(families)").fetchall()]
    desired = [
        "resident_id",
        "floor",
        "head_name",
        "head_cnic",
        "head_phone",
        "member_count",
    ]
    sel = [c for c in desired if c in cols]
    df = pd.read_sql_query(f"SELECT {', '.join(sel)} FROM families", get_conn())
    for col in desired:
        if col not in df.columns:
            df[col] = "" if col in [
                "floor",
                "head_name",
                "head_cnic",
                "head_phone",
            ] else 0
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_bills() -> pd.DataFrame:
    if not table_exists("bills"):
        return pd.DataFrame()
    cols = [c[1] for c in get_conn().execute("PRAGMA table_info(bills)").fetchall()]
    has_paid = "is_paid" in cols
    sel = [
        "id",
        "resident_id",
        "billing_month",
        "COALESCE(water_bill,0)      AS water_bill",
        "COALESCE(security_bill,0)   AS security_bill",
        "COALESCE(sanitation_bill,0) AS sanitation_bill",
    ]
    if has_paid:
        sel.append("is_paid")
    df = pd.read_sql_query(f"SELECT {', '.join(sel)} FROM bills", get_conn())
    if not has_paid:
        df["is_paid"] = 0
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_contributions() -> pd.DataFrame:
    if not (table_exists("contributions") and table_exists("funds")):
        return pd.DataFrame()
    sql = """
        SELECT c.resident_id,
               f.fund_title,
               f.fund_month,
               c.amount
          FROM contributions AS c
          JOIN funds         AS f ON f.id = c.fund_id
    """
    return pd.read_sql_query(sql, get_conn())


@st.cache_data(ttl=300, show_spinner=False)
def load_funds_summary() -> pd.DataFrame:
    if not table_exists("funds"):
        return pd.DataFrame()
    sql = """
        SELECT f.id,
               f.fund_title,
               f.fund_month,
               COALESCE(SUM(c.amount),0) AS total_amt,
               COUNT(c.resident_id)      AS n_contrib
          FROM funds              AS f
     LEFT JOIN contributions AS c ON f.id = c.fund_id
      GROUP BY f.id
      ORDER BY f.fund_month DESC, f.fund_title
    """
    return pd.read_sql_query(sql, get_conn())


# ────────────────────────────────────────────────────────────
# 3. Widgets / Global filters
# ────────────────────────────────────────────────────────────

def filters() -> dict:
    col_s, col_d, col_f = st.columns([2, 3, 3])

    streets = col_s.multiselect("Street(s)", STREETS, placeholder="All")
    today = date.today()
    default_from = date(today.year, 1, 1)
    d_from, d_to = col_d.date_input(
        "Date range (month-based)",
        (default_from, today),
        format="YYYY/MM/DD",
    )
    facilities = col_f.multiselect(
        "Facility filter",
        ["Water", "Security", "Sanitation"],
        placeholder="Any",
    )
    st.divider()
    return {
        "streets": streets,
        "from": d_from,
        "to": d_to,
        "facilities": facilities,
    }


# ────────────────────────────────────────────────────────────
# 4. KPI strip (added Houses & Streets)
# ────────────────────────────────────────────────────────────

def show_kpis(res, houses_cnt, funds_sum, bills, contrib):
    tot_res = len(res)
    billed = collected = 0
    funds_amt = contrib["amount"].sum() if not contrib.empty else 0

    if not bills.empty:
        billed = bills[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1).sum()
        collected = bills.loc[
            bills["is_paid"].astype(bool),
            ["water_bill", "security_bill", "sanitation_bill"],
        ].sum(axis=1).sum()

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Streets", f"{len(STREETS)}")
    c2.metric("Houses", f"{houses_cnt}")
    c3.metric("Residents", f"{tot_res}")
    c4.metric("Billed", f"{billed:,.0f}")
    c5.metric("Collected", f"{collected:,.0f}")
    c6.metric("Funds", f"{funds_amt:,.0f}")
    c7.metric("Recovery %", f"{collected / billed * 100:,.1f} %" if billed else "—")


# ────────────────────────────────────────────────────────────
# 5. Main page
# ────────────────────────────────────────────────────────────

def render():
    st.header("📊 View Data")

    # ─── manual refresh ───
    with st.sidebar:
        if st.button("🔄 Refresh data"):
            st.cache_data.clear()
            st.experimental_rerun()

    global filt
    filt = filters()

    # ---- data & filter application ----
    residents = load_residents()
    if filt["streets"]:
        residents = residents[residents["street_name"].isin(filt["streets"])]
    if filt["facilities"]:
        for fac in filt["facilities"]:
            residents = residents[residents[f"facility_{fac.lower()}"]]

    families = load_families()
    bills = load_bills()
    contributions = load_contributions()
    funds_sum = load_funds_summary()

    # Pre‑computations for overview
    houses_df = residents[["street_name", "house_no"]].drop_duplicates()
    houses_cnt = len(houses_df)

    # Global KPI strip
    show_kpis(residents, houses_cnt, funds_sum, bills, contributions)

    # ---- Tabs ----
    (
        tab_over,
        tab_summary,
        tab_res,
        tab_fam,
        tab_bill,
        tab_fund,
        tab_trend,
        tab_age,
        tab_cov,
        tab_out,
    ) = st.tabs(
        [
            "Town Overview",
            "Resident Summary",
            "Residents",
            "Families",
            "Bills",
            "Funds",
            "Trends",
            "Aging",
            "Coverage",
            "Outstanding",
        ]
    )

    dfs: dict[str, pd.DataFrame] = {}  # for sidebar export

    # ───────────────────  0. Town Overview  ───────────────────
    with tab_over:
        st.session_state["active_tab"] = "Town Overview"

        st.subheader("🏘️ Houses per Street")
        houses_per_street = (
            houses_df.groupby("street_name").size().reindex(STREETS, fill_value=0).reset_index(name="Houses")
        )
        st.dataframe(houses_per_street, hide_index=True, use_container_width=True)
        dfs["Town Overview"] = houses_per_street

        # ── Bills summary ──
        st.subheader("🧾 Monthly Bill Collection")
        if bills.empty:
            st.info("No bills data on record.")
        else:
            bills["total_amt"] = bills[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
            bill_month = (
                bills.groupby("billing_month")
                .apply(
                    lambda df: pd.Series(
                        {
                            "total_billed": df["total_amt"].sum(),
                            "total_collected": df[df["is_paid"].astype(bool)]["total_amt"].sum(),
                            "people_paid": int(df["is_paid"].astype(bool).sum()),
                        }
                    )
                )
                .reset_index()
            )
            bill_month["people_left"] = len(residents) - bill_month["people_paid"]
            st.dataframe(bill_month, hide_index=True, use_container_width=True)

            # Per street recovery
            st.subheader("📈 Street‑wise Bill Recovery")
            bills_res = bills.merge(residents[["resident_id", "street_name"]], on="resident_id", how="left")
            res_per_street = residents.groupby("street_name").size()
            paid_per_street = bills_res.groupby("street_name")["is_paid"].sum()
            bill_street = (
                pd.DataFrame({
                    "people_paid": paid_per_street,
                    "people_left": res_per_street - paid_per_street,
                })
                .reindex(STREETS, fill_value=0)
                .reset_index()
                .rename(columns={"index": "street_name"})
            )
            st.dataframe(bill_street, hide_index=True, use_container_width=True)

        # ── Funds summary ──
        st.subheader("💰 Funds Overview")
        if funds_sum.empty:
            st.info("No fund data.")
        else:
            funds_ext = funds_sum.copy()
            funds_ext["n_left"] = len(residents) - funds_ext["n_contrib"]
            funds_ext = funds_ext.rename(columns={
                "fund_title": "Fund",
                "fund_month": "Month",
                "total_amt": "Collected (Rs)",
                "n_contrib": "Contributors",
                "n_left": "Outstanding",
            })
            st.dataframe(funds_ext, hide_index=True, use_container_width=True)

    # ───────────────────  1. Resident Summary  ───────────────────
    # (unchanged apart from tab index)
    with tab_summary:
        st.session_state["active_tab"] = "Resident Summary"
        if residents.empty:
            st.info("No resident data available.")
        else:
            option_map = {
                f"{row.house_no} – {row.owner_name}": rid
                for rid, row in residents.sort_values("house_no").iterrows()
            }
            sel = st.selectbox("Select resident", list(option_map.keys()))
            rid = option_map[sel]
            r = residents.loc[rid]

            st.subheader("👤 Profile")
            prof = pd.Series(
                {
                    "House #": r.house_no,
                    "Street": r.street_name,
                    "Owner": r.owner_name,
                    "Phone": r.owner_phone,
                    "Rented": "Yes" if r.is_rent else "No",
                    "Facilities": ", ".join(
                        [svc for svc in ["Water", "Security", "Sanitation"] if r[f"facility_{svc.lower()}"]]
                    )
                    or "None",
                },
                name="Details",
            )
            st.table(prof)

            st.subheader("👪 Family / Lessee")
            fam_r = families[families["resident_id"] == rid]
            if fam_r.empty:
                st.info("No family data.")
            else:
                st.dataframe(
                    fam_r.drop(columns=["resident_id"]),
                    hide_index=True,
                    use_container_width=True,
                )

            st.subheader("🧾 Bills")
            bill_r = bills[bills["resident_id"] == rid].copy()
            if bill_r.empty:
                st.info("No bills.")
            else:
                bill_r["Total"] = bill_r[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
                st.dataframe(
                    bill_r[
                        [
                            "billing_month",
                            "water_bill",
                            "security_bill",
                            "sanitation_bill",
                            "Total",
                            "is_paid",
                        ]
                    ].rename(columns={"billing_month": "Month", "is_paid": "Paid"}),
                    hide_index=True,
                    use_container_width=True,
                )

            st.subheader("💰 Fund contributions")
            cont_r = contributions[contributions["resident_id"] == rid]
            if cont_r.empty:
                st.info("No fund history.")
            else:
                st.dataframe(
                    cont_r.drop(columns=["resident_id"]).rename(
                        columns={
                            "fund_title": "Fund",
                            "fund_month": "Month",
                            "amount": "Amount",
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

    # ───────────────────  Remaining tabs  ───────────────────
    # (code identical to v3, only offset indices)

    # Residents
    with tab_res:
        st.session_state["active_tab"] = "Residents"
        st.dataframe(
            residents.drop(columns=["resident_id"]).reset_index(drop=True),
            use_container_width=True,
        )
        dfs["Residents"] = residents

    # Families
    with tab_fam:
        st.session_state["active_tab"] = "Families"
        if families.empty:
            st.info("No families table.")
        else:
            fam_view = (
                residents[["resident_id", "house_no", "street_name"]]
                .merge(families, on="resident_id", how="right")
                .drop(columns=["resident_id"])
            )
            st.dataframe(fam_view, use_container_width=True, hide_index=True)
            dfs["Families"] = fam_view

    # Bills
    with tab_bill:
        st.session_state["active_tab"] = "Bills"
        if bills.empty:
            st.info("No bills table.")
        else:
            bills["Total"] = bills[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
            bview = bills.merge(
                residents[["resident_id", "house_no", "street_name"]],
                on="resident_id",
                how="left",
            )
            st.dataframe(bview, use_container_width=True, hide_index=True)
            dfs["Bills"] = bview

    # Funds
    with tab_fund:
        st.session_state["active_tab"] = "Funds"
        if funds_sum.empty:
            st.info("No funds data.")
        else:
            st.dataframe(funds_sum, use_container_width=True, hide_index=True)
            dfs["Funds"] = funds_sum

    # Trends (unchanged)
    with tab_trend:
        st.session_state["active_tab"] = "Trends"
        if bills.empty:
            st.info("No data for trends.")
        else:
            trend = (
                bills.groupby("billing_month")[["water_bill", "security_bill", "sanitation_bill"]]
                .sum()
                .sum(axis=1)
                .reset_index(name="Total")
                .sort_values("billing_month")
            )
            fig, ax = plt.subplots()
            ax.plot(trend["billing_month"], trend["Total"], marker="o")
            ax.set_ylabel("Amount (Rs)")
            ax.set_xlabel("Month")
            plt.xticks(rotation=45)
            st.pyplot(fig, use_container_width=True)
            dfs["Trends"] = trend

    # Aging
    with tab_age:
        st.session_state["active_tab"] = "Aging"
        if bills.empty:
            st.info("No bills table.")
        else:
            due = bills[~bills["is_paid"].astype(bool)].copy()
            if due.empty:
                st.info("No outstanding bills.")
            else:
                today = pd.Timestamp.today().normalize()
                due["month_dt"] = pd.to_datetime(due["billing_month"], format="%Y-%m")
                due["due_date"] = due["month_dt"] + pd.offsets.MonthEnd(0)
                due["days"] = (today - due["due_date"]).dt.days.clip(lower=0)

                def bucket(d):
                    if d <= 30:
                        return "0-30"
                    if d <= 60:
                        return "31-60"
                    if d <= 90:
                        return "61-90"
                    return "90+"

                buckets = due["days"].apply(bucket).value_counts().reindex(
                    ["0-30", "31-60", "61-90", "90+"], fill_value=0
                )
                fig, ax = plt.subplots()
                ax.bar(buckets.index, buckets.values)
                ax.set_ylabel("Bills")
                ax.set_xlabel("Days overdue")
                st.pyplot(fig, use_container_width=True)
                dfs["Aging"] = due

    # Coverage
    with tab_cov:
        st.session_state["active_tab"] = "Coverage"
        if residents.empty:
            st.info("No resident data.")
        else:
            cov = (
                residents.groupby("street_name")[[
                    "facility_water",
                    "facility_security",
                    "facility_sanitation",
                ]]
                .mean()
                .sort_index()
            )
            mat = (cov.values * 100).round(1)
            fig, ax = plt.subplots(figsize=(6, 8))
            im = ax.imshow(mat, aspect="auto")
            ax.set_xticks(range(3))
            ax.set_xticklabels(["Water", "Security", "Sanitation"])
            ax.set_yticks(range(len(cov)))
            ax.set_yticklabels(cov.index)
            for i in range(len(cov)):
                for j in range(3):
                    ax.text(
                        j,
                        i,
                        f"{mat[i, j]:.0f}%",
                        ha="center",
                        va="center",
                        color="white" if mat[i, j] > 50 else "black",
                        fontsize=8,
                    )
            ax.set_title("Facility coverage (%)")
            st.pyplot(fig, use_container_width=True)
            dfs["Coverage"] = cov

    # Outstanding
    with tab_out:
        st.session_state["active_tab"] = "Outstanding"
        if bills.empty:
            st.info("No bills table.")
        else:
            out = bills[bills["is_paid"] == 0].copy()
            out["Total"] = out[["water_bill", "security_bill", "sanitation_bill"]].sum(axis=1)
            out = out.merge(
                residents[["resident_id", "house_no", "street_name"]],
                on="resident_id",
                how="left",
            )
            st.dataframe(out, use_container_width=True, hide_index=True)
            dfs["Outstanding"] = out

    # ───────────────────  Sidebar quick actions  ───────────────────
    with st.sidebar.expander("⚡ Quick actions", expanded=False):
        cur_tab = st.session_state.get("active_tab", "Residents")
        df_now = dfs.get(cur_tab)
        if df_now is not None and not df_now.empty:
            st.download_button(
                f"⬇ Export {cur_tab}",
                df_now.to_csv(index=False).encode(),
                file_name=f"{cur_tab.lower()}_{date.today()}.csv",
                mime="text/csv",
            )
            st.button("🖨 Print", on_click=lambda: st.experimental_js("window.print()"))

        if (
            cur_tab == "Outstanding"
            and st.session_state.get("role") == "admin"
            and df_now is not None
            and not df_now.empty
        ):
            phones = (
                df_now.merge(residents[["resident_id", "owner_phone"]], on="resident_id")["owner_phone"]
                .dropna()
                .unique()
            )
            if len(phones):
                wa_link = (
                    "https://wa.me/?text="
                    "Dear%20resident%2C%20your%20Ghouri%20Town%20bill%20is%20overdue."
                )
                st.markdown(f"[💬 Message defaulters ({len(phones)})]({wa_link})", unsafe_allow_html=True)

    # ───────────────────  Footer timestamp  ───────────────────
    if table_exists("bills"):
        ts = get_conn().execute("SELECT MAX(billing_month) FROM bills").fetchone()[0]
        if ts:
            st.caption(f"Latest billing month on record: {ts}")


# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    render()
