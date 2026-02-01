# enter_data.py — Ghouri Town Phase 1 (Admin → Enter Member Data)
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import List, Dict, Any, Optional

import streamlit as st

# ────────────────────────────────────────────────────────────────────────────────
# 1) DB: schema + helpers
# ────────────────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "residents.db"  # same convention as before

CREATE_RESIDENTS = """
CREATE TABLE IF NOT EXISTS residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_no           TEXT NOT NULL UNIQUE,
    street_name        TEXT NOT NULL,
    owner_name         TEXT NOT NULL,
    owner_cnic         TEXT NOT NULL,
    owner_phone        TEXT NOT NULL,
    is_rent            INTEGER NOT NULL DEFAULT 0,   -- House-level: derived from family floors
    lessee_name        TEXT,
    lessee_cnic        TEXT,
    lessee_phone       TEXT,
    floors             INTEGER NOT NULL DEFAULT 1,
    facility_water     INTEGER NOT NULL DEFAULT 0,
    facility_security  INTEGER NOT NULL DEFAULT 0,
    facility_sanitation INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_FAMILIES = """
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL,
    floor        INTEGER NOT NULL,
    head_name    TEXT NOT NULL,
    head_cnic    TEXT NOT NULL,
    head_phone   TEXT NOT NULL,
    is_rent      INTEGER NOT NULL DEFAULT 0, -- per-floor tenancy flag
    FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
);
"""

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = 1")
    return conn

def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

def init_db() -> None:
    with closing(get_connection()) as conn:
        conn.executescript(CREATE_RESIDENTS + CREATE_FAMILIES)
        ensure_column(conn, "families", "is_rent", "INTEGER NOT NULL DEFAULT 0")
        conn.commit()

# ────────────────────────────────────────────────────────────────────────────────
# 2) Insert logic
# ────────────────────────────────────────────────────────────────────────────────

def _insert_resident(data: Dict[str, Any], families: List[Dict[str, Any]]) -> int:
    """Insert a resident & its family entries atomically. House is_rent is derived."""
    conn = get_connection()
    try:
        with closing(conn.cursor()) as cur:
            any_floor_rented = int(any(bool(f.get("is_rent")) for f in families))
            cur.execute(
                """
                INSERT INTO residents (
                    house_no, street_name,
                    owner_name, owner_cnic, owner_phone,
                    is_rent, lessee_name, lessee_cnic, lessee_phone,
                    floors, facility_water, facility_security, facility_sanitation
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    data["house_no"].strip(),
                    data["street_name"].strip(),
                    data["owner_name"].strip(),
                    data["owner_cnic"].strip(),
                    data["owner_phone"].strip(),
                    any_floor_rented,
                    (data.get("lessee_name") or None),
                    (data.get("lessee_cnic") or None),
                    (data.get("lessee_phone") or None),
                    int(data["floors"]),
                    int(data["facility_water"]),
                    int(data["facility_security"]),
                    int(data["facility_sanitation"]),
                ),
            )
            resident_id = cur.lastrowid

            for fam in families:
                cur.execute(
                    """
                    INSERT INTO families (resident_id, floor, head_name, head_cnic, head_phone, is_rent)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        resident_id,
                        int(fam["floor"]),
                        fam["name"].strip(),
                        fam["cnic"].strip(),
                        fam["phone"].strip(),
                        int(bool(fam.get("is_rent", False))),
                    ),
                )
        conn.commit()
        return resident_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ────────────────────────────────────────────────────────────────────────────────
# 3) UI (Streamlit)
# ────────────────────────────────────────────────────────────────────────────────

def _header() -> None:
    st.title("🏠 Ghouri Town Phase‑1 — Admin: Enter Member Data")
    st.caption("Add owner details and per‑floor family info. Rent is tracked per floor.")

def _street_options() -> List[str]:
    """Fetch distinct streets already present; returns [] if none."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT DISTINCT street_name FROM residents WHERE street_name IS NOT NULL AND TRIM(street_name) <> '' ORDER BY street_name ASC"
        ).fetchall()
    return [r[0] for r in rows]

def _owner_form() -> Dict[str, Any]:
    st.subheader("Owner / House Details")

    # ── Row 1 (2 columns): House No | Street/Block (selectbox with 'Add new...') ──
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        house_no = st.text_input("House No*", placeholder="e.g., GT‑1/23", key="house_no")
    with r1c2:
        streets = _street_options()
        # Include a sentinel and an 'Add new...' option
        options = ["— Select —", "➕ Add new..."] + streets
        street_choice = st.selectbox("Street / Block*", options=options, index=0, key="street_choice")
        new_street = ""
        if street_choice == "➕ Add new...":
            new_street = st.text_input("Enter new Street / Block*", placeholder="e.g., Street 4, Block A", key="street_new")
        street_name = (
            new_street.strip() if street_choice == "➕ Add new..." else ("" if street_choice == "— Select —" else street_choice)
        )

    # ── Row 2 (2 columns): Owner Name | Owner CNIC ──
    r2c1, r2c2 = st.columns(2)
    with r2c1:
        owner_name = st.text_input("Owner Name*", placeholder="e.g., Ahmed Khan", key="owner_name")
    with r2c2:
        owner_cnic = st.text_input("Owner CNIC*", placeholder="xxxxx-xxxxxxx-x", key="owner_cnic")

    # ── Row 3 (2 columns): Owner Phone | Floors ──
    r3c1, r3c2 = st.columns(2)
    with r3c1:
        owner_phone = st.text_input("Owner Phone*", placeholder="03xx-xxxxxxx", key="owner_phone")
    with r3c2:
        floors = st.number_input("Number of Floors*", min_value=1, max_value=6, value=1, step=1, key="floors")

    st.markdown("**Facilities**")
    c1, c2, c3 = st.columns(3)
    with c1:
        facility_water = st.checkbox("Water", value=False, key="facility_water")
    with c2:
        facility_security = st.checkbox("Security", value=False, key="facility_security")
    with c3:
        facility_sanitation = st.checkbox("Sanitation", value=False, key="facility_sanitation")

    return {
        "house_no": house_no,
        "street_name": street_name,
        "floors": int(floors),
        "owner_name": owner_name,
        "owner_cnic": owner_cnic,
        "owner_phone": owner_phone,
        "facility_water": facility_water,
        "facility_security": facility_security,
        "facility_sanitation": facility_sanitation,
        # Kept for compatibility with existing DB columns; set to None
        "lessee_name": None,
        "lessee_cnic": None,
        "lessee_phone": None,
    }

def _families_form(floors: int) -> List[Dict[str, Any]]:
    st.subheader("Family Details Per Floor")
    families_input: List[Dict[str, Any]] = []
    for floor in range(1, int(floors) + 1):
        with st.expander(f"Floor {floor} — Family Info", expanded=(int(floors) == 1)):
            fam_name = st.text_input("Head of Family Name*", key=f"fam_name_{floor}")
            fam_cnic = st.text_input("Head CNIC*", key=f"fam_cnic_{floor}")
            fam_phone = st.text_input("Contact Phone*", key=f"fam_phone_{floor}")
            fam_is_rent = st.checkbox("Is this floor on rent?", key=f"fam_is_rent_{floor}")
            families_input.append(
                {"floor": floor, "name": fam_name, "cnic": fam_cnic, "phone": fam_phone, "is_rent": fam_is_rent}
            )
    return families_input

def _validate_owner(data: Dict[str, Any]) -> Optional[str]:
    required = ["house_no", "street_name", "owner_name", "owner_cnic", "owner_phone"]
    for k in required:
        if not data.get(k):
            return f"Please fill required field: **{k.replace('_',' ').title()}**"
    return None

def _validate_families(families: List[Dict[str, Any]]) -> Optional[str]:
    for fam in families:
        if not all([fam.get("name"), fam.get("cnic"), fam.get("phone")]):
            return "Please provide COMPLETE family info (name, CNIC, phone) for every floor."
    return None

def render() -> None:
    init_db()
    _header()

    with st.form("enter_member_form", clear_on_submit=False):
        data = _owner_form()
        families_input = _families_form(data["floors"])

        st.divider()
        submitted = st.form_submit_button("💾 Save Record", use_container_width=True)

        if submitted:
            # Validate
            msg = _validate_owner(data) or _validate_families(families_input)
            if msg:
                st.error(f"⚠️ {msg}")
                st.stop()

            try:
                resident_id = _insert_resident(data, families_input)
                st.success(f"✅ Saved! Resident ID: {resident_id}")
            except sqlite3.IntegrityError as ie:
                if "UNIQUE constraint failed: residents.house_no" in str(ie):
                    st.error("❌ House No already exists. Please use a unique House No.")
                else:
                    st.error(f"❌ DB Integrity error: {ie}")
            except Exception as e:
                st.error(f"❌ Failed to save record: {e}")

    # Footer: small stats
    with closing(get_connection()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    st.caption(f"**Total residents stored:** {total}")

# ────────────────────────────────────────────────────────────────────────────────
# Entrypoint for `streamlit run`
# ────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    render()
