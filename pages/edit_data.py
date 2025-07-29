"""
Ghouri Town Dashboard · Resident Editor
──────────────────────────────────────────
Allows the admin to **fully edit** an existing resident record *and* their
per‑floor family‑head details – without violating Streamlit’s “no nested
expanders” rule (we now use *tabs* for floors).

Key features
• Inline selector → open editor for any house.
• Update resident meta, rent/lessee data, facilities, floor count.
• Tabbed UI for each floor’s family info (adds/removes as floor count changes).
• Single‑click save writes `residents` and `families` in one transaction.
"""
from pathlib import Path
import sqlite3

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
    df[bool_cols] = df[bool_cols].astype(bool)
    return df


def load_families(resident_id: int) -> pd.DataFrame:
    q = """
        SELECT floor, head_name, head_cnic, head_phone
          FROM families
         WHERE resident_id = ?
         ORDER BY floor
    """
    return pd.read_sql_query(q, get_conn(), params=(resident_id,))


# ──────────────────────────────────────────────────────────────────────
# 2. DB mutation helper
# ──────────────────────────────────────────────────────────────────────

def update_resident_and_families(res_id: int, res_data: dict, fam_list: list[dict]):
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
            INSERT INTO families (resident_id, floor, head_name, head_cnic, head_phone)
            VALUES (?,?,?,?,?)
            """,
            [
                (res_id, fam["floor"], fam["name"].strip(), fam["cnic"].strip(), fam["phone"].strip())
                for fam in fam_list
            ],
        )


# ──────────────────────────────────────────────────────────────────────
# 3. Streamlit page
# ──────────────────────────────────────────────────────────────────────

def render():
    st.header("📝 Edit Resident Data")

    # 3‑A  Row selector ------------------------------------------------
    df = load_residents()
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
            # -- Basic house / owner ----------------------------------
            c1, c2 = st.columns(2)
            house_no = c1.text_input("House No.", value=row["house_no"], key=f"house_{rid}")
            street   = c2.text_input("Street",   value=row["street_name"], key=f"street_{rid}")

            st.markdown("#### Owner")
            o1, o2, o3 = st.columns(3)
            owner_name  = o1.text_input("Owner name",  value=row["owner_name"],  key=f"oname_{rid}")
            owner_cnic  = o2.text_input("Owner CNIC",  value=row["owner_cnic"],  key=f"ocnic_{rid}")
            owner_phone = o3.text_input("Owner phone", value=row["owner_phone"], key=f"ophone_{rid}")

            # -- Rent toggle ------------------------------------------
            is_rent = st.checkbox("Is Rent?", value=row["is_rent"], key=f"rent_{rid}")
            lessee_name = lessee_cnic = lessee_phone = ""
            if is_rent:
                st.markdown("#### Lessee")
                l1, l2, l3 = st.columns(3)
                lessee_name  = l1.text_input("Lessee name",  value=row["lessee_name"] or "",  key=f"lname_{rid}")
                lessee_cnic  = l2.text_input("Lessee CNIC",  value=row["lessee_cnic"] or "",  key=f"lcnic_{rid}")
                lessee_phone = l3.text_input("Lessee phone", value=row["lessee_phone"] or "", key=f"lphone_{rid}")

            # -- Floors & families ------------------------------------
            floors = st.number_input("Floors", min_value=1, value=int(row["floors"]), step=1, key=f"floors_{rid}")

            fam_df = load_families(rid)
            fam_map = {int(r.floor): r for r in fam_df.itertuples(index=False)}

            st.subheader("Family Details (one per floor)")
            tab_objs = st.tabs([f"Floor {fl}" for fl in range(1, int(floors) + 1)])
            families_input: list[dict] = []
            for tab, fl in zip(tab_objs, range(1, int(floors) + 1)):
                defaults = fam_map.get(fl)
                with tab:
                    name  = st.text_input("Head name", value=defaults.head_name if defaults else "", key=f"fname_{rid}_{fl}")
                    cnic  = st.text_input("CNIC",      value=defaults.head_cnic if defaults else "", key=f"fcnic_{rid}_{fl}")
                    phone = st.text_input("Phone",     value=defaults.head_phone if defaults else "", key=f"fphone_{rid}_{fl}")
                    families_input.append({"floor": fl, "name": name, "cnic": cnic, "phone": phone})

            # -- Facilities -------------------------------------------
            fac_default = [f for f, v in zip(
                ["Water", "Security", "Sanitation"],
                [row["facility_water"], row["facility_security"], row["facility_sanitation"]],
            ) if v]
            facilities = st.multiselect("Facilities", ["Water", "Security", "Sanitation"], default=fac_default, key=f"fac_{rid}")

            # -- Save button ------------------------------------------
            if st.button("💾 Save changes", key=f"save_{rid}"):
                # Validation
                if not house_no or not owner_name:
                    st.error("House No. and Owner name are required.")
                    st.stop()
                if is_rent and not all([lessee_name, lessee_cnic, lessee_phone]):
                    st.error("Complete lessee details required for rented houses.")
                    st.stop()
                if any(not all([f["name"], f["cnic"], f["phone"]]) for f in families_input):
                    st.error("Please fill family info for *every* floor.")
                    st.stop()

                res_payload = {
                    "house_no": house_no.strip(),
                    "street_name": street.strip(),
                    "owner_name": owner_name.strip(),
                    "owner_cnic": owner_cnic.strip(),
                    "owner_phone": owner_phone.strip(),
                    "is_rent": int(is_rent),
                    "lessee_name": lessee_name.strip() if is_rent else None,
                    "lessee_cnic": lessee_cnic.strip() if is_rent else None,
                    "lessee_phone": lessee_phone.strip() if is_rent else None,
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
