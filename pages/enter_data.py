import sqlite3
from contextlib import closing
from pathlib import Path
import streamlit as st

# ────────────────────────────────────────────────────────────────────────────────
# 1. DB helpers
# ────────────────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).parent.parent / "residents.db"

CREATE_RESIDENTS = """
CREATE TABLE IF NOT EXISTS residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    house_no           TEXT NOT NULL UNIQUE,
    street_name        TEXT NOT NULL,
    owner_name         TEXT NOT NULL,
    owner_cnic         TEXT NOT NULL,
    owner_phone        TEXT NOT NULL,
    is_rent            INTEGER NOT NULL,
    lessee_name        TEXT,
    lessee_cnic        TEXT,
    lessee_phone       TEXT,
    floors             INTEGER NOT NULL,
    facility_water     INTEGER NOT NULL,
    facility_security  INTEGER NOT NULL,
    facility_sanitation INTEGER NOT NULL,
    created_at         TEXT DEFAULT CURRENT_TIMESTAMP
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
    FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
);
"""

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("PRAGMA foreign_keys = 1")
        conn.executescript(CREATE_RESIDENTS + CREATE_FAMILIES)
        conn.commit()

@st.cache_resource(show_spinner=False)
def get_connection():
    init_db()
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# ────────────────────────────────────────────────────────────────────────────────
# 2. Insert helper
# ────────────────────────────────────────────────────────────────────────────────

STREETS = [
    "Al‑Rehman Road", "Ali Road", "Habib Road", "Bilal Road", "Khadija Road",
] + [f"Street {i}" for i in range(1, 23)]  # 1 … 22


def _insert_resident(data: dict, families: list[dict]):
    """Insert resident & related families in *one* transaction."""
    conn = get_connection()
    try:
        with closing(conn.cursor()) as cur:
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
                    data["street_name"],
                    data["owner_name"].strip(),
                    data["owner_cnic"].strip(),
                    data["owner_phone"].strip(),
                    int(data["is_rent"]),
                    (data.get("lessee_name") or None),
                    (data.get("lessee_cnic") or None),
                    (data.get("lessee_phone") or None),
                    data["floors"],
                    int(data["facility_water"]),
                    int(data["facility_security"]),
                    int(data["facility_sanitation"]),
                ),
            )
            resident_id = cur.lastrowid

            for fam in families:
                cur.execute(
                    """
                    INSERT INTO families (resident_id, floor, head_name, head_cnic, head_phone)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        resident_id,
                        fam["floor"],
                        fam["name"].strip(),
                        fam["cnic"].strip(),
                        fam["phone"].strip(),
                    ),
                )
        conn.commit()
        return resident_id
    except Exception:
        conn.rollback()
        raise

# ────────────────────────────────────────────────────────────────────────────────
# 3. Streamlit UI (dynamic widgets / no st.form)
# ────────────────────────────────────────────────────────────────────────────────

def render():
    """Render the Streamlit page."""

    # ── 0. Handle post‑save reset BEFORE any widgets are created ───────────
    if st.session_state.pop("reset_form", False):
        # Delete all per‑form keys so widgets start fresh
        for k in list(st.session_state.keys()):
            if k not in ("logged_in", "role", "username"):
                del st.session_state[k]

    st.header("🏠 Enter Resident Data – Dynamic Form")

    # ── Basic house info ────────────────────────────────────────────────────
    house_no = st.text_input("House No. (must be unique)", key="house_no")
    street_name = st.selectbox("Select Street / Road", STREETS, key="street_name")

    # ── Owner details ───────────────────────────────────────────────────────
    st.subheader("Owner Details")
    owner_name = st.text_input("Owner Name", key="owner_name")
    owner_cnic = st.text_input("Owner CNIC", key="owner_cnic")
    owner_phone = st.text_input("Owner Phone #", key="owner_phone")

    # ── Rent toggle (dynamic) ───────────────────────────────────────────────
    is_rent = st.checkbox("Is the house on rent?", key="is_rent")

    lessee_name = lessee_cnic = lessee_phone = ""
    if is_rent:
        st.subheader("Lessee Details")
        lessee_name = st.text_input("Lessee Name", key="lessee_name")
        lessee_cnic = st.text_input("Lessee CNIC", key="lessee_cnic")
        lessee_phone = st.text_input("Lessee Phone #", key="lessee_phone")

    # ── Floors & families – dynamic on floor count ─────────────────────────
    floors = st.number_input("No. of Floors", min_value=1, step=1, value=1, format="%d", key="floors")

    st.subheader("Family Details (required for EACH floor)")
    families_input: list[dict] = []
    for floor in range(1, int(floors) + 1):
        with st.expander(f"Floor {floor} – Family Info", expanded=(int(floors) == 1)):
            fam_name = st.text_input("Family Head Name", key=f"fam_name_{floor}")
            fam_cnic = st.text_input("CNIC", key=f"fam_cnic_{floor}")
            fam_phone = st.text_input("Phone", key=f"fam_phone_{floor}")
            families_input.append({
                "floor": floor,
                "name": fam_name,
                "cnic": fam_cnic,
                "phone": fam_phone,
            })

    # ── Facilities ─────────────────────────────────────────────────────────
    facilities = st.multiselect(
        "Facilities In Use",
        ["Water", "Security", "Sanitation"],
        default=["Water", "Security", "Sanitation"],
        key="facilities",
    )
    facility_water = "Water" in facilities
    facility_security = "Security" in facilities
    facility_sanitation = "Sanitation" in facilities

    # ── Save button (acts like submit) ─────────────────────────────────────
    if st.button("💾 Save Record"):
        # 1. Validation -----------------------------------------------------
        if not all([house_no, street_name, owner_name, owner_cnic, owner_phone]):
            st.error("⚠️  Please fill in all mandatory owner & house fields.")
            st.stop()

        if is_rent and not all([lessee_name, lessee_cnic, lessee_phone]):
            st.error("⚠️  Lessee details are required for rented houses.")
            st.stop()

        missing_fams = [f for f in families_input if not all([f["name"], f["cnic"], f["phone"]])]
        if missing_fams:
            st.error("⚠️  Please provide COMPLETE family info for every floor.")
            st.stop()

        # 2. Prepare payload ------------------------------------------------
        data = {
            "house_no": house_no,
            "street_name": street_name,
            "owner_name": owner_name,
            "owner_cnic": owner_cnic,
            "owner_phone": owner_phone,
            "is_rent": is_rent,
            "lessee_name": lessee_name,
            "lessee_cnic": lessee_cnic,
            "lessee_phone": lessee_phone,
            "floors": int(floors),
            "facility_water": facility_water,
            "facility_security": facility_security,
            "facility_sanitation": facility_sanitation,
        }

        # 3. DB insert ------------------------------------------------------
        try:
            resident_id = _insert_resident(data, families_input)
            st.success(f"✅ Record saved! Resident ID: {resident_id}")
            st.balloons()

            # 4. Flag for reset and rerun -----------------------------------
            st.session_state["reset_form"] = True
            st.rerun()

        except sqlite3.IntegrityError:
            st.error("❌ House number already exists. Please use a unique house number.")
        except Exception as e:
            st.error(f"❌ Failed to save record: {e}")

    # ── Footer count ───────────────────────────────────────────────────────
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    st.caption(f"**Total residents stored:** {total}")

# ────────────────────────────────────────────────────────────────────────────────
# Entrypoint for `streamlit run`
# ────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    render()
