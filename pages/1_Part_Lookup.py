"""Page 1 – Part Lookup: enter a part number and trigger research."""

import logging

import streamlit as st

from src.agents.database_agent import DatabaseAgent
from src.agents.research_agent import ResearchAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def reset_session() -> None:
    for key in [
        "current_part_number",
        "current_part_id",
        "research_result",
        "questionnaire_data",
        "user_answers",
        "current_assessment_id",
        "assessment_result",
    ]:
        st.session_state.pop(key, None)


# ── UI ─────────────────────────────────────────────────────────────────────────
st.title("🔍 Part Lookup")
st.markdown(
    "Enter a spare part number or code to begin the criticality assessment workflow."
)

with st.form("part_lookup_form"):
    col1, col2 = st.columns([3, 1])
    with col1:
        part_number = st.text_input(
            "Part Number / Code",
            placeholder="e.g. 6SE7021-8TB61, 3RV2011-1AA10, PMP-101",
            help="Enter the manufacturer part number, SKU, or internal code",
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("🔎 Research Part", use_container_width=True)

if submitted:
    if not part_number.strip():
        st.warning("Please enter a part number.")
    else:
        reset_session()
        st.session_state.current_part_number = part_number.strip()

        with st.spinner(f"Researching **{part_number}** online — this may take 15–30 seconds..."):
            try:
                agent = ResearchAgent()
                result = agent.research_part(part_number.strip())

                db_agent = DatabaseAgent()
                part_id = db_agent.upsert_part(result)
                db_agent.save_part_attributes(part_id, result)
                db_agent.save_research_sources(part_id, result)

                st.session_state.current_part_id = part_id
                st.session_state.research_result = result

                if result.source_urls:
                    st.success(
                        f"✅ Research complete — found {len(result.source_urls)} sources "
                        f"(confidence: {result.overall_confidence:.0%})"
                    )
                else:
                    st.warning(
                        "⚠️ Web search returned no results for this part.  \n"
                        "This is common in WSL / corporate networks where DuckDuckGo is blocked.  \n"
                        "**You can still proceed** — the questionnaire will ask you for the details manually.  \n\n"
                        "**To enable reliable search**, add a free SerpAPI key to your `.env`:  \n"
                        "`SERPAPI_KEY=your_key`  → get one at https://serpapi.com (100 free/month)"
                    )

            except Exception as exc:
                logger.exception("Research failed")
                st.error(f"Research error: {exc}")

# ── Show previously researched part if session is active ──────────────────────
if "current_part_number" in st.session_state:
    st.markdown("---")
    st.markdown(f"**Active part:** `{st.session_state.current_part_number}`")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📊 View Research Results", use_container_width=True):
            st.switch_page("pages/2_Research_Results.py")
    with col2:
        if st.button("📋 Go to Questionnaire", use_container_width=True):
            st.switch_page("pages/3_Questionnaire.py")
    with col3:
        if st.button("🔄 New Assessment", use_container_width=True):
            reset_session()
            st.rerun()

# ── Recent parts quick-start ───────────────────────────────────────────────────
st.markdown("---")
st.subheader("📜 Recent Assessments")
try:
    db_agent = DatabaseAgent()
    recent = db_agent.list_assessments(limit=5)
    if recent:
        for rec in recent:
            label_color = (
                "🔴" if rec["label"] == "Critical"
                else ("🟡" if rec["label"] == "Semi Critical" else "🟢")
            )
            col1, col2, col3, col4 = st.columns([2, 3, 2, 2])
            col1.code(rec["part_number"])
            col2.write(rec["part_name"] or "—")
            col3.write(f"{label_color} {rec['label']}")
            col4.write(f"Score: {rec['total_score']:.0f}/100")
    else:
        st.info("No assessments yet. Enter a part number above to begin.")
except Exception:
    st.info("No assessment history available.")
