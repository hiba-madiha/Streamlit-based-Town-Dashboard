"""
Ghouri Town Dashboard · Resident Editor (Updated for per-floor rent flags + street dropdown)
──────────────────────────────────────────
- Each floor has "Is this floor on rent?" (house is_rent derived automatically)
- Street/Block is a dropdown (distinct streets from DB) with "➕ Add new…" option
- Owner/House layout uses 3 rows × 2 columns:
    Row 1: House No | Street/Block (dropdown)
    Row 2: Owner Name | Owner CNIC
    Row 3: Owner Phone | Floors
"""
from pathlib import Path
import sqlite3
from typing import List, Dict, Any

import pandas as pd
import streamlit as st

# ──────────────────────────────────────────────────────────────────────
# 0. DB helpers
# ──────────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent.parent / "residents.db"


def get_conn() -> sqlite3.Connection:
    if "_db_conn" not in st.session_state:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = 1")
        st.session_state["_db_conn"] = conn
    return st.session_state["_db_conn"]


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing SQLite table if it doesn't already exist."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def ensure_schema() -> None:
    """Lightweight migration to guarantee `families.is_rent` exists."""
    conn = get_conn()
    ensure_column(conn, "families", "is_rent", "INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _street_options() -> List[str]:
    """Fetch distinct, non-empty streets currently present in DB."""
    rows = get_conn().execute(
        "SELECT DISTINCT street_name FROM residents "
        "WHERE street_name IS NOT NULL AND TRIM(street_name) <> '' "
        "ORDER BY street_name ASC"
    ).fetchall()
    return [r[0] for r in rows]


# ──────────────────────────────────────────────────────────────────────
# 1. Cached loaders
# ──────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_residents() -> pd.DataFrame:
    q = """
        SELECT id, house_no, street_name,
               owner_name, owner_cnic, owner_phone,
               is_rent, lessee_name, lessee_cnic, lessee_phone,
               floors,
               facility_water, facility_security, facility_sanitation
          FROM residents
         ORDER BY id DESC
    """
    df = pd.read_sql_query(q, get_conn())
    bool_cols = ["is_rent", "facility_water", "facility_security", "facility_sanitation"]
    for c in bool_cols:
        if c in df.columns:
            df[c] = df[c].astype(bool)
    return df


def load_families(resident_id: int) -> pd.DataFrame:
    q = """
        SELECT floor, head_name, head_cnic, head_phone, is_rent
          FROM families
         WHERE resident_id = ?
         ORDER BY floor
    """
    df = pd.read_sql_query(q, get_conn(), params=(resident_id,))
    if "is_rent" in df.columns:
        df["is_rent"] = df["is_rent"].astype(bool)
    return df


# ──────────────────────────────────────────────────────────────────────
# 2. DB mutation helper
# ──────────────────────────────────────────────────────────────────────

def update_resident_and_families(res_id: int, res_data: Dict[str, Any], fam_list: List[Dict[str, Any]]):
    """
    Update resident and replace all families for that resident in a single transaction.
    Expects each `fam` in fam_list to include: floor, name, cnic, phone, is_rent (bool/int).
    """
    conn = get_conn()
    with conn:  # atomic transaction
        # a) Update resident
        sets = ", ".join(f"{k} = ?" for k in res_data.keys())
        vals = list(res_data.values()) + [res_id]
        conn.execute(f"UPDATE residents SET {sets} WHERE id = ?", vals)

        # b) Replace families wholesale
        conn.execute("DELETE FROM families WHERE resident_id = ?", (res_id,))
        conn.executemany(
            """
            INSERT INTO families (resident_id, floor, head_name, head_cnic, head_phone, is_rent)
            VALUES (?,?,?,?,?,?)
            """,
            [
                (res_id, fam["floor"], fam["name"].strip(), fam["cnic"].strip(),
                 fam["phone"].strip(), int(bool(fam.get("is_rent", False))))
                for fam in fam_list
            ],
        )


# ──────────────────────────────────────────────────────────────────────
# 3. Streamlit page
# ──────────────────────────────────────────────────────────────────────

def render():
    ensure_schema()  # Make sure families.is_rent exists before any reads

    st.header("📝 Edit Resident Data")

    # 3‑A  Row selector ------------------------------------------------
    df = load_residents()
    # Simple selector UX: add a checkbox column to pick which rows to edit
    df.insert(0, "Select", False)
    edited_df = st.data_editor(
        df,
        key="select_table",
        num_rows="fixed",
        use_container_width=True,
        disabled=[c for c in df.columns if c != "Select"],
        column_config={
            "Select": st.column_config.CheckboxColumn(label="Edit?", width="small"),
        },
    )
    picked = edited_df[edited_df["Select"]]
    if picked.empty:
        st.info("Tick **Edit?** beside a resident to modify their record.")
        return

    # 3‑B  Per‑resident editor ----------------------------------------
    for _, row in picked.iterrows():
        rid = int(row["id"])
        with st.expander(f"House {row['house_no']} — {row['street_name']}", expanded=True):
            # ── Row 1: House No | Street/Block (dropdown with 'Add new…') ──
            r1c1, r1c2 = st.columns(2)
            with r1c1:
                house_no = st.text_input("House No.", value=row["house_no"], key=f"house_{rid}")
            with r1c2:
                streets = _street_options()
                # Ensure current street is in the options to show it selected
                current_street = row["street_name"] or ""
                if current_street and current_street not in streets:
                    streets = [current_street] + streets
                options = ["— Select —", "➕ Add new…"] + streets
                try:
                    default_index = options.index(current_street) if current_street else 0
                except ValueError:
                    default_index = 0
                street_choice = st.selectbox("Street / Block*", options=options, index=default_index, key=f"street_choice_{rid}")
                new_street = ""
                if street_choice == "➕ Add new…":
                    new_street = st.text_input("Enter new Street / Block*", value="", placeholder="e.g., Street 4, Block A", key=f"street_new_{rid}")
                street_name = (
                    new_street.strip()
                    if street_choice == "➕ Add new…"
                    else ("" if street_choice == "— Select —" else street_choice)
                )

            # ── Row 2: Owner Name | Owner CNIC ──
            r2c1, r2c2 = st.columns(2)
            with r2c1:
                owner_name  = st.text_input("Owner name",  value=row["owner_name"],  key=f"oname_{rid}")
            with r2c2:
                owner_cnic  = st.text_input("Owner CNIC",  value=row["owner_cnic"],  key=f"ocnic_{rid}")

            # ── Row 3: Owner Phone | Floors ──
            r3c1, r3c2 = st.columns(2)
            with r3c1:
                owner_phone = st.text_input("Owner phone", value=row["owner_phone"], key=f"ophone_{rid}")
            with r3c2:
                floors = st.number_input("Floors", min_value=1, value=int(row["floors"]), step=1, key=f"floors_{rid}")

            # -- Families ---------------------------------------------
            fam_df = load_families(rid)
            fam_map = {int(r.floor): r for r in fam_df.itertuples(index=False)}

            st.subheader("Family Details (one per floor)")
            tab_objs = st.tabs([f"Floor {fl}" for fl in range(1, int(floors) + 1)])
            families_input: List[Dict[str, Any]] = []
            for tab, fl in zip(tab_objs, range(1, int(floors) + 1)):
                defaults = fam_map.get(fl)
                with tab:
                    name  = st.text_input("Head name", value=(defaults.head_name if defaults else ""), key=f"fname_{rid}_{fl}")
                    cnic  = st.text_input("CNIC",      value=(defaults.head_cnic if defaults else ""), key=f"fcnic_{rid}_{fl}")
                    phone = st.text_input("Phone",     value=(defaults.head_phone if defaults else ""), key=f"fphone_{rid}_{fl}")
                    # per-floor rent flag
                    fam_is_rent_default = bool(defaults.is_rent) if defaults and hasattr(defaults, "is_rent") else False
                    fam_is_rent = st.checkbox("Is this floor on rent?", value=fam_is_rent_default, key=f"f_isrent_{rid}_{fl}")
                    families_input.append({"floor": fl, "name": name, "cnic": cnic, "phone": phone, "is_rent": fam_is_rent})

            # -- Facilities -------------------------------------------
            fac_default = [f for f, v in zip(
                ["Water", "Security", "Sanitation"],
                [row["facility_water"], row["facility_security"], row["facility_sanitation"]],
            ) if v]
            facilities = st.multiselect("Facilities", ["Water", "Security", "Sanitation"], default=fac_default, key=f"fac_{rid}")

            # -- Save button ------------------------------------------
            if st.button("💾 Save changes", key=f"save_{rid}"):
                # Validation
                if not house_no or not owner_name or not street_name:
                    st.error("House No, Street/Block and Owner name are required.")
                    st.stop()
                if any(not all([f["name"], f["cnic"], f["phone"]]) for f in families_input):
                    st.error("Please fill family info for *every* floor.")
                    st.stop()

                # Derive house-level is_rent from per-floor flags
                derived_is_rent = int(any(bool(f.get("is_rent")) for f in families_input))

                res_payload = {
                    "house_no": house_no.strip(),
                    "street_name": street_name.strip(),
                    "owner_name": owner_name.strip(),
                    "owner_cnic": owner_cnic.strip(),
                    "owner_phone": owner_phone.strip(),
                    "is_rent": derived_is_rent,
                    # Lessee fields retained for schema compatibility but cleared here
                    "lessee_name": None,
                    "lessee_cnic": None,
                    "lessee_phone": None,
                    "floors": int(floors),
                    "facility_water": int("Water" in facilities),
                    "facility_security": int("Security" in facilities),
                    "facility_sanitation": int("Sanitation" in facilities),
                }

                try:
                    update_resident_and_families(rid, res_payload, families_input)
                    st.success("Updated!")
                    st.cache_data.clear()
                    st.rerun()
                except sqlite3.IntegrityError as e:
                    if "UNIQUE" in str(e).upper():
                        st.error("House number already exists.")
                    else:
                        st.error(f"DB error: {e}")


# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    render()
