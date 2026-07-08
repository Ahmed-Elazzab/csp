"""
Entry point – configures navigation and initialises the database.

Part Lookup is the default (first) page.  The old overview/dashboard has been
removed; the sidebar shows only the five workflow pages.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import logging

import streamlit as st

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Spare Part Criticality Assessment",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DB init (once per browser session, before any page renders) ────────────────
if not st.session_state.get("app_initialized"):
    try:
        from src.database.connection import init_db
        from src.ingestion.excel_importer import seed_database_if_empty

        init_db()
        seed_database_if_empty()
        st.session_state.app_initialized = True
        logger.info("Application initialised")
    except Exception as exc:
        logger.error("Init error: %s", exc)
        st.error(
            f"⚠️ **Database connection failed.**\n\n"
            f"1. Start PostgreSQL: `docker compose up -d`\n"
            f"2. Create a `.env` file (see `.env.example`)\n\n"
            f"Error: `{exc}`"
        )
        st.stop()

# ── Navigation (no "app" entry – sidebar starts directly at Part Lookup) ───────
pg = st.navigation(
    [
        st.Page("pages/1_Part_Lookup.py",        title="Part Lookup",       icon="🔍"),
        st.Page("pages/2_Research_Results.py",   title="Research Results",  icon="📊"),
        st.Page("pages/3_Questionnaire.py",      title="Questionnaire",     icon="📋"),
        st.Page("pages/4_Assessment_Result.py",  title="Assessment Result", icon="🎯"),
        st.Page("pages/5_History.py",            title="History",           icon="📜"),
    ]
)
pg.run()
