# main.py ---------------------------------------------------------------
import streamlit as st
from auth import authenticate
import importlib

st.set_page_config(
    page_title="Ghouri Town Portal",
    page_icon="🏠",
    initial_sidebar_state="collapsed",   # collapsed during login
)

# -------------------- Session bootstrap ------------------------------
if "logged_in" not in st.session_state:
    st.session_state.update({
        "logged_in": False,
        "role": None,
        "username": None,
    })

# -------------------- Login view -------------------------------------
if not st.session_state.logged_in:
    # Hide the (empty) sidebar completely with a touch of CSS
    st.markdown(
        """
        <style>[data-testid="stSidebar"] { display: none; }</style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### 🔐 Login")
        with st.form("login_form", clear_on_submit=True):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")

        if submitted:
            role = authenticate(username, password)
            if role:
                st.session_state.update(
                    logged_in=True,
                    role=role,
                    username=username,
                )
                st.rerun()
            else:
                st.error("❌ Invalid username or password")

    st.stop()   # nothing else on the page while logged-out

# ----------------------------------------------------------------------
# Logged-in area
# ----------------------------------------------------------------------
st.sidebar.header(
    f"👤 {st.session_state.username.title()}  ({st.session_state.role})"
)

# Menu options depend on role
if st.session_state.role == "admin":
    choice = st.sidebar.radio(
        "Navigate",
        [
            "Dashboard",
            "Enter Data",
            "Edit Data",
            "Delete Data",
            "Bill Entry",
            "Funds Entry",
            "View Data",
            "Defaulters",
            "Logout",
        ],
    )
else:  # regular user
    choice = st.sidebar.radio(
        "Navigate",
        [
            "Dashboard",
            "View Data",
            "Logout",
        ],
    )

# Handle logout early
if choice == "Logout":
    st.session_state.clear()
    st.rerun()

# Map menu text → module inside pages/
page_modules = {
    "Dashboard":  "dashboard",
    "Enter Data": "enter_data",
    "Edit Data":  "edit_data",
    "Delete Data": "delete_data",
    "Bill Entry": "bill_entry",
    "Funds Entry": "funds_entry",
    "View Data":  "view_data",
    "Defaulters": "defaulters"
}

module_name = page_modules.get(choice)
if module_name:
    page = importlib.import_module(f"pages.{module_name}")
    page.render()          # every page file exposes `render()`
