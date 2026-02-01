"""
view_data_updated2.py — Town Analytics & Explorer (floor-aware)
- Adds unique keys to all editors/buttons.
- Fixes "Slider min_value must be less than max_value" by only showing the slider when there are >=2 streets.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

DB_PATH = Path(__file__).parent.parent / "residents.db"


# ─────────────────────────── DB Helpers ────────────────────────────
def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


def table_exists(name: str) -> bool:
    row = get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)
    ).fetchone()
    return bool(row)


def load_residents() -> pd.DataFrame:
    sql = """
        SELECT id AS resident_id,
               house_no, street_name, owner_name, owner_phone,
               facility_water, facility_security, facility_sanitation,
               floors
        FROM residents
        ORDER BY street_name, house_no
    """
    return pd.read_sql_query(sql, get_conn()).set_index("resident_id")


def load_families() -> pd.DataFrame:
    if not table_exists("families"):
        return pd.DataFrame(columns=["resident_id","floor","head_name","head_phone","is_rent"])
    sql = """
        SELECT resident_id, floor, head_name, head_phone, is_rent
        FROM families
        ORDER BY resident_id, floor
    """
    df = pd.read_sql_query(sql, get_conn())
    if df.empty:
        return pd.DataFrame(columns=["resident_id","floor","head_name","head_phone","is_rent"])
    df["is_rent"] = df["is_rent"].fillna(0).astype(int)
    return df


def load_bill_lines_for_month(yyyymm: str) -> pd.DataFrame:
    if not table_exists("bill_lines"):
        return pd.DataFrame(columns=["resident_id","floor","water_bill","security_bill","sanitation_bill"]).set_index(["resident_id","floor"])
    sql = """
        SELECT resident_id, floor, water_bill, security_bill, sanitation_bill
        FROM bill_lines WHERE billing_month = ?
    """
    df = pd.read_sql_query(sql, get_conn(), params=(yyyymm,))
    if df.empty:
        return pd.DataFrame(columns=["resident_id","floor","water_bill","security_bill","sanitation_bill"]).set_index(["resident_id","floor"])
    return df.set_index(["resident_id","floor"])


def load_monthly_charges(yyyymm: str) -> Dict[str, float]:
    if not table_exists("monthly_charges"):
        return {"water_due": 0.0, "security_due": 0.0, "sanitation_due": 0.0}
    row = get_conn().execute(
        "SELECT water_due, security_due, sanitation_due FROM monthly_charges WHERE billing_month = ?",
        (yyyymm,),
    ).fetchone()
    if not row:
        return {"water_due": 0.0, "security_due": 0.0, "sanitation_due": 0.0}
    return {"water_due": float(row[0]), "security_due": float(row[1]), "sanitation_due": float(row[2])}


def load_distinct_streets() -> List[str]:
    try:
        rows = get_conn().execute("SELECT DISTINCT street_name FROM residents ORDER BY street_name").fetchall()
        return [r[0] for r in rows if r[0] not in (None, "")]
    except Exception:
        return []


# ──────────────────────── Unit View Builder ────────────────────────
def build_units_df(residents: pd.DataFrame, families: pd.DataFrame) -> pd.DataFrame:
    """
    Build per-unit dataframe honoring rules:
      - Owner unit exists only if there is ≥1 non-rented floor (families.is_rent == 0).
      - Each rented floor (is_rent == 1) is its own unit.
    """
    fam = families.copy()

    # Rented floors → one unit each
    rented = fam[fam["is_rent"] == 1].copy()
    if not rented.empty:
        rented = rented.merge(
            residents.reset_index()[
                ["resident_id", "house_no", "street_name", "owner_name", "owner_phone",
                 "facility_water", "facility_security", "facility_sanitation"]
            ],
            on="resident_id", how="left",
        )
        rented["unit_ref"]   = rented.apply(lambda r: f"{r['house_no']} — F{int(r['floor'])}", axis=1)
        rented["head_name"]  = rented["head_name"].fillna("")
        rented["head_phone"] = rented["head_phone"].fillna("")
        rented = rented[[
            "resident_id", "floor", "unit_ref",
            "street_name", "owner_name", "head_name", "head_phone",
            "facility_water", "facility_security", "facility_sanitation",
        ]]

    # Owner rows only for residents with >=1 non-rented floor
    non_rent = fam[fam["is_rent"] == 0]
    owner_residents = set(non_rent["resident_id"].unique())
    if owner_residents:
        owners = residents.loc[residents.index.isin(owner_residents)].reset_index()[
            ["resident_id", "house_no", "street_name", "owner_name", "owner_phone",
             "facility_water", "facility_security", "facility_sanitation"]
        ].copy()
        owners["floor"]      = 0
        owners["unit_ref"]   = owners["house_no"] + " — F0 (Owner)"
        owners["head_name"]  = owners["owner_name"]
        owners["head_phone"] = owners["owner_phone"]
        owners = owners[[
            "resident_id", "floor", "unit_ref",
            "street_name", "owner_name", "head_name", "head_phone",
            "facility_water", "facility_security", "facility_sanitation",
        ]]
    else:
        owners = pd.DataFrame(columns=[
            "resident_id", "floor", "unit_ref",
            "street_name", "owner_name", "head_name", "head_phone",
            "facility_water", "facility_security", "facility_sanitation",
        ])

    units = pd.concat([owners, rented], ignore_index=True)

    # Fallback: if no family rows exist → single owner row per resident
    if units.empty:
        fallback = residents.reset_index()[
            ["resident_id", "house_no", "street_name", "owner_name", "owner_phone",
             "facility_water", "facility_security", "facility_sanitation"]
        ].copy()
        fallback["floor"]      = 0
        fallback["unit_ref"]   = fallback["house_no"] + " — F0 (Owner)"
        fallback["head_name"]  = fallback["owner_name"]
        fallback["head_phone"] = fallback["owner_phone"]
        units = fallback[[
            "resident_id", "floor", "unit_ref",
            "street_name", "owner_name", "head_name", "head_phone",
            "facility_water", "facility_security", "facility_sanitation",
        ]]

    units = units.set_index(["resident_id", "floor"]).sort_index()
    return units


# ───────────────────────── Scope Utilities ─────────────────────────
def months_between(start: Tuple[int,int], end: Tuple[int,int]) -> List[str]:
    sy, sm = start; ey, em = end
    out = []
    y, m = sy, sm
    while (y < ey) or (y == ey and m <= em):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1; y += 1
    return out


def charges_sum_for_scope(months: List[str]) -> Dict[str, float]:
    total = {"water_due": 0.0, "security_due": 0.0, "sanitation_due": 0.0}
    for mm in months:
        ch = load_monthly_charges(mm)
        for k in total:
            total[k] += float(ch.get(k, 0.0) or 0.0)
    return total


def payments_sum_for_scope(months: List[str]) -> pd.DataFrame:
    """
    Returns DataFrame indexed by (resident_id, floor) with columns water_paid, security_paid, sanitation_paid
    summed across given months from bill_lines.
    """
    frames = []
    for mm in months:
        lines = load_bill_lines_for_month(mm).copy()
        if lines.empty:
            continue
        lines.rename(columns={
            "water_bill":"water_paid",
            "security_bill":"security_paid",
            "sanitation_bill":"sanitation_paid"
        }, inplace=True)
        frames.append(lines)
    if not frames:
        return pd.DataFrame(columns=["water_paid","security_paid","sanitation_paid"]).astype(float)
    agg = pd.concat(frames).groupby(level=[0,1]).sum()
    return agg[["water_paid","security_paid","sanitation_paid"]]


# ───────────────────────────── KPIs ────────────────────────────────
def kpi_card(label: str, value, help_text: Optional[str] = None):
    st.metric(label, value, help=help_text)


# ─────────────────────────────── UI ────────────────────────────────
def render():
    st.header("📊 View & Analyze — Ghouri Town")

    # Global filters
    with st.expander("Filters", expanded=True):
        scope = st.radio("Scope", ["Monthly", "Range", "Annual"], horizontal=True)
        today = date.today().replace(day=1)

        if scope == "Monthly":
            m_dt = st.date_input("Month", value=today, format="YYYY/MM/DD")
            months = [m_dt.strftime("%Y-%m")]
        elif scope == "Annual":
            yr = st.selectbox("Year", list(reversed(range(today.year-5, today.year+1))))
            months = [f"{yr}-{m:02d}" for m in range(1,13)]
        else:  # Range
            c1, c2 = st.columns(2)
            start = c1.date_input("Start month", value=today.replace(month=1), format="YYYY/MM/DD")
            end   = c2.date_input("End month", value=today, format="YYYY/MM/DD")
            months = months_between((start.year, start.month), (end.year, end.month))

        streets_all = load_distinct_streets()
        streets = st.multiselect("Street/Block", streets_all, default=[])

        st.write("Service filter:")
        c1, c2, c3 = st.columns(3)
        f_w = c1.checkbox("Water", True)
        f_s = c2.checkbox("Security", True)
        f_t = c3.checkbox("Sanitation", True)

        unit_type = st.selectbox("Unit type", ["Owner units only", "Rented floors only", "Both"], index=2)
        show_only = st.selectbox("Show only", ["All", "With dues", "With payments"], index=0)

    # Base data
    residents = load_residents()
    families  = load_families()
    units     = build_units_df(residents, families)                    # index: (resident_id, floor)
    if streets:
        units = units[units["street_name"].isin(streets)]

    # Eligibility flags already present per house
    charges_total = charges_sum_for_scope(months)                       # dict
    pays = payments_sum_for_scope(months)                               # DF indexed by (rid,floor)
    for col in ["water_paid","security_paid","sanitation_paid"]:
        units[col] = pays[col].reindex(units.index, fill_value=0.0)

    # Dues per unit for selected scope
    units["water_due"]      = units["facility_water"]      * charges_total["water_due"]
    units["security_due"]   = units["facility_security"]   * charges_total["security_due"]
    units["sanitation_due"] = units["facility_sanitation"] * charges_total["sanitation_due"]

    # Service visibility
    svc_cols_due = []; svc_cols_paid = []
    if f_w: svc_cols_due.append("water_due");       svc_cols_paid.append("water_paid")
    if f_s: svc_cols_due.append("security_due");    svc_cols_paid.append("security_paid")
    if f_t: svc_cols_due.append("sanitation_due");  svc_cols_paid.append("sanitation_paid")

    units["due_sum"]  = units[svc_cols_due].sum(axis=1)   if svc_cols_due  else 0.0
    units["paid_sum"] = units[svc_cols_paid].sum(axis=1)  if svc_cols_paid else 0.0
    units["pending"]  = units["due_sum"] - units["paid_sum"]

    # Unit type filter
    if unit_type == "Owner units only":
        units = units.reset_index(); units = units[units["floor"] == 0].set_index(["resident_id","floor"])
    elif unit_type == "Rented floors only":
        units = units.reset_index(); units = units[units["floor"] != 0].set_index(["resident_id","floor"])

    # Show-only filter
    if show_only == "With dues":
        units = units[units["due_sum"] > 0]
    elif show_only == "With payments":
        units = units[units["paid_sum"] > 0]

    # ───────────────────────── KPIs ─────────────────────────
    total_houses = len(residents)
    total_units  = len(units)
    rented_units = (units.reset_index()["floor"] != 0).sum()
    rented_pct   = (rented_units / total_units * 100) if total_units else 0.0
    charges_set_months = sum(1 for mm in months if any(load_monthly_charges(mm).values()))
    collection_rate = (units["paid_sum"].sum() / units["due_sum"].sum() * 100) if units["due_sum"].sum() > 0 else 0.0
    total_pending = units["pending"].clip(lower=0).sum()

    c1, c2, c3 = st.columns(3)
    kpi_card("Total houses", total_houses)
    kpi_card("Total units (after filters)", total_units)
    kpi_card("% rented units", f"{rented_pct:.1f}%")

    c4, c5, c6 = st.columns(3)
    kpi_card("Months with charges set", f"{charges_set_months}/{len(months)}")
    kpi_card("Collection rate", f"{collection_rate:.1f}%")
    kpi_card("Total pending", f"{int(total_pending):,}")

    st.divider()

    # ─────────────── Collections & dues (time series) ───────────────
    st.subheader("Due vs Paid over time")
    monthly_rows = []
    for mm in months:
        ch = load_monthly_charges(mm)
        du = pd.Series(0.0, index=units.index)
        if f_w: du += units["facility_water"]      * (ch.get("water_due",0.0) or 0.0)
        if f_s: du += units["facility_security"]   * (ch.get("security_due",0.0) or 0.0)
        if f_t: du += units["facility_sanitation"] * (ch.get("sanitation_due",0.0) or 0.0)
        due_total = float(du.sum())

        lines = load_bill_lines_for_month(mm)
        paid = 0.0
        if not lines.empty:
            lines = lines.reindex(units.index, fill_value=0.0)
            paid += lines["water_bill"].sum() if f_w else 0.0
            paid += lines["security_bill"].sum() if f_s else 0.0
            paid += lines["sanitation_bill"].sum() if f_t else 0.0

        monthly_rows.append({"month": mm, "due": due_total, "paid": float(paid)})

    monthly_df = pd.DataFrame(monthly_rows)
    if not monthly_df.empty:
        fig = plt.figure(figsize=(6,3.5))
        plt.plot(monthly_df["month"], monthly_df["due"], marker="o", label="Due")
        plt.plot(monthly_df["month"], monthly_df["paid"], marker="o", label="Paid")
        plt.xticks(rotation=45, ha="right")
        plt.title("Due vs Paid")
        plt.legend()
        st.pyplot(fig)

    st.divider()

    # ─────────────── Street/Block performance ───────────────
    st.subheader("Street/Block performance")
    street_pivot = units.reset_index().groupby("street_name").agg(
        Due=("due_sum","sum"),
        Paid=("paid_sum","sum"),
        Pending=("pending","sum")
    )
    street_pivot["Collection%"] = np.where(street_pivot["Due"]>0, (street_pivot["Paid"]/street_pivot["Due"]*100), 0.0)
    st.data_editor(street_pivot.sort_values("Pending", ascending=False), use_container_width=True, disabled=True, key="street_pivot_editor")

    # Safe slider: only show if there are >=2 streets
    street_count = len(street_pivot)
    if street_count >= 2:
        topN = st.slider("Show top N pending streets", 1, street_count, min(5, street_count), key="topN_slider")
    else:
        topN = street_count  # 0 or 1; no slider
        if street_count == 1:
            st.caption("Only one street available — showing it below.")
        else:
            st.caption("No streets available in current filters.")

    if street_count > 0:
        top_df = street_pivot.sort_values("Pending", ascending=False).head(topN).reset_index()
        fig2 = plt.figure(figsize=(6,3.5))
        plt.bar(top_df["street_name"], top_df["Pending"])
        plt.xticks(rotation=45, ha="right")
        plt.title("Top pending streets")
        st.pyplot(fig2)

    st.divider()

    # ───────────── Unit mix & rent insight ─────────────
    st.subheader("Unit mix & rent insight")
    units_reset = units.reset_index()
    n_owner  = (units_reset["floor"] == 0).sum()
    n_rented = (units_reset["floor"] != 0).sum()
    c1, c2 = st.columns(2)
    c1.metric("Owner units", n_owner)
    c2.metric("Rented units", n_rented)
    floors_series = families[families["is_rent"] == 1]["floor"].value_counts().sort_index()
    if not floors_series.empty:
        fig3 = plt.figure(figsize=(6,3.5))
        plt.bar(floors_series.index.astype(str), floors_series.values)
        plt.title("Distribution of rented floors")
        st.pyplot(fig3)

    st.divider()

    # ───────────── Defaulters deep dive ─────────────
    st.subheader("Defaulters (per unit)")
    defaulters = units[units["pending"] > 0].copy()
    if defaulters.empty:
        st.success("🎉 No defaulters in current filters/scope.")
    else:
        view = defaulters.reset_index()
        view.insert(0, "S.No", range(1, len(view)+1))
        cols = ["S.No","unit_ref","street_name","owner_name","head_name","head_phone","due_sum","paid_sum","pending"]
        cfg = {
            "S.No": st.column_config.NumberColumn("S.No", disabled=True, format="%.0f"),
            "unit_ref":    st.column_config.TextColumn("House & Floor", disabled=True),
            "street_name": st.column_config.TextColumn("Street", disabled=True),
            "owner_name":  st.column_config.TextColumn("Owner", disabled=True),
            "head_name":   st.column_config.TextColumn("Head", disabled=True),
            "head_phone":  st.column_config.TextColumn("Head Phone", disabled=True),
            "due_sum":     st.column_config.NumberColumn("Due", disabled=True, format="%.0f"),
            "paid_sum":    st.column_config.NumberColumn("Paid", disabled=True, format="%.0f"),
            "pending":     st.column_config.NumberColumn("Pending", disabled=True, format="%.0f"),
        }
        st.data_editor(view[cols], hide_index=True, column_config=cfg, use_container_width=True, disabled=cols, key="defaulters_editor")

        csv = view[cols].to_csv(index=False).encode()
        st.download_button("Download defaulters CSV", csv, file_name="defaulters_units.csv", mime="text/csv", key="defaulters_csv_btn")

    st.divider()

    # ───────────── Facilities uptake & impact ─────────────
    st.subheader("Facilities uptake & impact")
    fac = residents[["facility_water","facility_security","facility_sanitation"]].mean()*100
    fac_df = pd.DataFrame({"Service": fac.index.str.replace("facility_",""), "Uptake%": fac.values})
    st.data_editor(fac_df.set_index("Service"), disabled=True, use_container_width=True, key="facilities_uptake_editor")

    for svc, flag in [("Water","facility_water"), ("Security","facility_security"), ("Sanitation","facility_sanitation")]:
        with st.expander(f"{svc}: subscribed vs not — dues & pending", expanded=False):
            temp = units.reset_index().copy()
            temp["Subscribed"] = np.where(temp[flag]==1, "Yes", "No")
            grp = temp.groupby("Subscribed").agg(Due=("due_sum","sum"), Pending=("pending","sum"))
            st.data_editor(grp, disabled=True, use_container_width=True, key=f"svc_compare_{svc.lower()}")

    st.divider()

    # ───────────── House/Unit explorer ─────────────
    st.subheader("House / Unit explorer")
    q = st.text_input("Search (house no / owner / head / phone contains):", "", key="search_box")
    search_df = units.reset_index()
    if q:
        ql = q.lower()
        mask = (
            search_df["unit_ref"].str.lower().str.contains(ql)
            | search_df["owner_name"].str.lower().str.contains(ql, na=False)
            | search_df["head_name"].str.lower().str.contains(ql, na=False)
            | search_df["head_phone"].astype(str).str.lower().str.contains(ql, na=False)
            | search_df["street_name"].str.lower().str.contains(ql, na=False)
        )
        search_df = search_df[mask]
    options = [f"{r.unit_ref} | {r.owner_name} / {r.head_name or '—'}" for _, r in search_df.iterrows()]
    sel = st.selectbox("Select unit", ["—"] + options, key="unit_selectbox")
    if sel != "—":
        idx = options.index(sel)
        row = search_df.iloc[idx]
        rid, fl = int(row["resident_id"]), int(row["floor"])
        st.write(f"**Owner:** {row['owner_name']}  |  **Head:** {row['head_name']}  |  **Phone:** {row['head_phone']}  |  **Street:** {row['street_name']}")

        months_sorted = sorted(months)
        paid_series = []
        due_series = []
        for mm in months_sorted:
            ch = load_monthly_charges(mm)
            due = 0.0
            if f_w: due += (row["facility_water"]      * (ch.get("water_due",0.0) or 0.0))
            if f_s: due += (row["facility_security"]   * (ch.get("security_due",0.0) or 0.0))
            if f_t: due += (row["facility_sanitation"] * (ch.get("sanitation_due",0.0) or 0.0))
            due_series.append(due)
            lines = load_bill_lines_for_month(mm)
            paid = 0.0
            if (rid, fl) in lines.index:
                if f_w: paid += float(lines.loc[(rid,fl),"water_bill"])
                if f_s: paid += float(lines.loc[(rid,fl),"security_bill"])
                if f_t: paid += float(lines.loc[(rid,fl),"sanitation_bill"])
            paid_series.append(paid)

        fig4 = plt.figure(figsize=(6,3.5))
        plt.plot(months_sorted, due_series, marker="o", label="Due")
        plt.plot(months_sorted, paid_series, marker="o", label="Paid")
        plt.xticks(rotation=45, ha="right")
        plt.title(f"Unit trend — {row['unit_ref']}")
        plt.legend()
        st.pyplot(fig4)

    st.divider()

    # ───────────── Data health ─────────────
    st.subheader("Data health & completeness")
    missing = [mm for mm in months if sum(load_monthly_charges(mm).values()) == 0]
    if missing:
        st.warning("Months missing charges: " + ", ".join(missing))
    else:
        st.success("Monthly charges exist for all months in scope.")

    # Incomplete contacts
    missing_contacts = units[(units["head_phone"].isna()) | (units["head_phone"].astype(str).str.strip() == "")]
    st.write(f"Units missing head phone: {len(missing_contacts)}")
    if len(missing_contacts):
        st.data_editor(missing_contacts.reset_index()[["unit_ref","street_name","owner_name","head_name"]], disabled=True, use_container_width=True, key="missing_contacts_editor")

    st.divider()

    # ───────────── Funds analytics (if present) ─────────────
    st.subheader("Funds analytics")
    if table_exists("funds") and table_exists("contributions"):
        try:
            # Introspect funds table to find name/date columns
            fund_cols = [r[1] for r in get_conn().execute("PRAGMA table_info(funds)")]
            name_col = next((c for c in ("title","name","fund_name","label") if c in fund_cols), None)
            created_col = next((c for c in ("created_at","created_on","date","timestamp","created") if c in fund_cols), None)

            select_cols = ["id"]
            if name_col: select_cols.append(name_col)
            if created_col: select_cols.append(created_col)
            funds_sql = "SELECT " + ", ".join(select_cols) + " FROM funds"
            funds = pd.read_sql_query(funds_sql, get_conn())

            # Normalize names for display
            if name_col and name_col != "title":
                funds.rename(columns={name_col: "title"}, inplace=True)
            if created_col and created_col != "created_at":
                funds.rename(columns={created_col: "created_at"}, inplace=True)
            if "title" not in funds.columns:
                funds["title"] = "Fund #" + funds["id"].astype(str)
            if "created_at" not in funds.columns:
                funds["created_at"] = None

            # Introspect contributions table
            contr_cols = [r[1] for r in get_conn().execute("PRAGMA table_info(contributions)")]
            fund_fk = next((c for c in ("fund_id","fund","fundId","fundID","fundid") if c in contr_cols), None)
            amount_col = next((c for c in ("amount","value","paid","total","contribution") if c in contr_cols), None)
            cdate_col = next((c for c in ("created_at","created_on","date","timestamp","created") if c in contr_cols), None)

            if (fund_fk is None) or (amount_col is None):
                st.warning("Contributions table is missing expected columns; showing funds list only.")
                funds_view = funds.set_index("id").assign(Collected=0.0)
                st.data_editor(funds_view, disabled=True, use_container_width=True, key="funds_table_editor")
            else:
                cols = [f"{fund_fk} AS fund_id", f"{amount_col} AS amount"]
                if cdate_col: cols.append(f"{cdate_col} AS created_at")
                contr_sql = "SELECT " + ", ".join(cols) + " FROM contributions"
                contr = pd.read_sql_query(contr_sql, get_conn())

                total_by_fund = contr.groupby("fund_id")["amount"].sum().rename("Collected") if not contr.empty else pd.Series(dtype=float)
                funds_view = funds.set_index("id").join(total_by_fund, how="left").fillna({"Collected":0}).sort_values("Collected", ascending=False)
                st.data_editor(funds_view, disabled=True, use_container_width=True, key="funds_table_editor")

                # Contributions over time chart (only if we have a date column)
                if "created_at" in contr.columns and not contr.empty:
                    contr["month"] = contr["created_at"].astype(str).str[:7]
                    csum = contr.groupby("month")["amount"].sum().reset_index()
                    if not csum.empty:
                        fig5 = plt.figure(figsize=(6,3.5))
                        plt.plot(csum["month"], csum["amount"], marker="o")
                        plt.xticks(rotation=45, ha="right")
                        plt.title("Funds collected over time")
                        st.pyplot(fig5)
                else:
                    st.caption("Contributions lack a date column; skipping over-time chart.")
        except Exception as e:
            st.error(f"Could not render funds analytics: {e}")
    else:
        st.caption("Funds tables not found; skipping funds analytics.")


    st.divider()

    # ───────────── Exports & snapshot ─────────────
    st.subheader("Exports & snapshot")
    export_def = units.reset_index()[["resident_id","floor","unit_ref","street_name","owner_name","head_name","head_phone","due_sum","paid_sum","pending"]]
    st.download_button("Download current view (CSV)", export_def.to_csv(index=False).encode(), file_name="view_units.csv", mime="text/csv", key="view_csv_btn")

    if st.button("Build snapshot (zip)", key="snapshot_btn"):
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            monthly_rows2 = []
            for mm in months:
                ch = load_monthly_charges(mm)
                du = pd.Series(0.0, index=units.index)
                if f_w: du += units["facility_water"]      * (ch.get("water_due",0.0) or 0.0)
                if f_s: du += units["facility_security"]   * (ch.get("security_due",0.0) or 0.0)
                if f_t: du += units["facility_sanitation"] * (ch.get("sanitation_due",0.0) or 0.0)
                due_total = float(du.sum())
                lines = load_bill_lines_for_month(mm)
                paid = 0.0
                if not lines.empty:
                    lines = lines.reindex(units.index, fill_value=0.0)
                    paid += lines["water_bill"].sum() if f_w else 0.0
                    paid += lines["security_bill"].sum() if f_s else 0.0
                    paid += lines["sanitation_bill"].sum() if f_t else 0.0
                monthly_rows2.append({"month": mm, "due": due_total, "paid": float(paid)})
            monthly_df2 = pd.DataFrame(monthly_rows2)

            z.writestr("units_view.csv", export_def.to_csv(index=False))
            z.writestr("street_pivot.csv", street_pivot.to_csv())
            z.writestr("monthly_due_paid.csv", monthly_df2.to_csv(index=False) if not monthly_df2.empty else "month,due,paid\n")
        st.download_button("Download snapshot.zip", buf.getvalue(), file_name="snapshot.zip", mime="application/zip", key="snapshot_zip_btn")

    st.caption("Tip: adjust filters at the top to slice by month range, streets, services, and unit type.")


if __name__ == "__main__":
    render()
