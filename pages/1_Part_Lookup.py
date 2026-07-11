"""Page 1 – Part Lookup: enter a part number and trigger research."""

import logging

import streamlit as st

from src.agents.database_agent import DatabaseAgent
from src.agents.research_agent import ResearchAgent
from src.utils.helpers import ResearchResult

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
        "submitted_answers",
    ]:
        st.session_state.pop(key, None)


def _save_part_stub(part_number: str) -> int:
    """Save a minimal part record to DB without any research, return part_id."""
    result = ResearchResult(part_number=part_number)
    db_agent = DatabaseAgent()
    part_id = db_agent.upsert_part(result)
    st.session_state.current_part_number = part_number
    st.session_state.current_part_id = part_id
    st.session_state.research_result = result
    return part_id


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
            placeholder="e.g. SS-1F0-3GC, 6SE7021-8TB61, PMP-101",
            help="Enter the manufacturer part number, SKU, or internal code",
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("🔎 Research Part", use_container_width=True)
        skip_submitted = st.form_submit_button(
            "⚡ Skip Research",
            use_container_width=True,
            help="Go straight to the questionnaire and enter part details manually. "
                 "Use this when web search is unavailable (corporate / offline networks).",
        )

# ── Skip Research path ─────────────────────────────────────────────────────────
if skip_submitted:
    if not part_number.strip():
        st.warning("Please enter a part number first.")
    else:
        reset_session()
        _save_part_stub(part_number.strip())
        st.info(
            "⚡ Skipping web research.  \n"
            "The questionnaire will ask you for all part details manually."
        )

# ── Research path ──────────────────────────────────────────────────────────────
if submitted:
    if not part_number.strip():
        st.warning("Please enter a part number.")
    else:
        reset_session()
        st.session_state.current_part_number = part_number.strip()

        timeout_secs = 12
        with st.spinner(f"Searching for **{part_number}** — will give up after {timeout_secs} s if network is blocked..."):
            try:
                agent = ResearchAgent()
                result = agent.research_part(part_number.strip())

                db_agent = DatabaseAgent()
                part_id = db_agent.upsert_part(result)
                db_agent.save_part_attributes(part_id, result)
                db_agent.save_research_sources(part_id, result)

                st.session_state.current_part_id = part_id
                st.session_state.research_result = result

            except Exception as exc:
                logger.exception("Research failed")
                st.error(f"Research error: {exc}")
                result = None

        # ── Show result or blocked-network guidance ────────────────────────────
        if result is not None:
            if result.source_urls:
                st.success(
                    f"✅ Research complete — {len(result.source_urls)} sources found "
                    f"(confidence: {result.overall_confidence:.0%})"
                )
            else:
                st.warning(
                    "⚠️ **Web search returned no results** — your network appears to be "
                    "blocking outbound requests (common in corporate / WSL environments)."
                )
                st.markdown("#### To fix web search — add a search API key to `.env`")
                col_t, col_s = st.columns(2)
                with col_t:
                    st.info(
                        "**Tavily** *(recommended)*  \n"
                        "AI-native search, 1 000 free searches/month  \n"
                        "[Get key → app.tavily.com](https://app.tavily.com)  \n\n"
                        "```\nTAVILY_API_KEY=tvly-xxx\n```"
                    )
                with col_s:
                    st.info(
                        "**SerpAPI** *(alternative)*  \n"
                        "Google-backed, 100 free searches/month  \n"
                        "[Get key → serpapi.com](https://serpapi.com)  \n\n"
                        "```\nSERPAPI_KEY=your_key\n```"
                    )
                st.markdown("---")
                st.markdown("**Or proceed without web search — answer all questions manually:**")
                if st.button("📋 Go to Questionnaire (manual entry)", type="primary", use_container_width=True):
                    st.switch_page("pages/3_Questionnaire.py")

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
