# pages/dashboard.py
# ─────────────────────────────────────────────────────────────
import streamlit as st

def render():
    st.markdown(
        """
        <div style="text-align:center; padding:2rem 0;">
            <h1 style="font-size:2.8rem; margin-bottom:0.4rem;">
                🌟 WELCOME TO 🌟 
            </h1>
            <h1 style="font-size:2.8rem; margin-bottom:0.4rem;">
                GHOURI TOWN PHASE 1
            </h1>
            <h1 style="font-size:2.8rem; margin-bottom:0.4rem;">
                DASHBOARD
            </h1>
            <p style="font-size:1.2rem; color:#666;">
                Your one-stop portal for resident records, bills, and community funds.
            </p>
            <hr style="width:60%; margin:2rem auto;">
            <p style="font-size:1rem; line-height:1.6; max-width:600px; margin:0 auto; color:#444;">
                Use the sidebar to navigate between sections.<br>
                • <strong>Residents</strong> – manage household profiles<br>
                • <strong>Bills</strong> – record and track monthly dues<br>
                • <strong>Funds</strong> – oversee community fund-raising<br>
                • <strong>View Data</strong> – explore detailed reports &amp; trends
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
