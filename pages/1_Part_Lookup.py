"""
NWC Spare Part Criticality Assessment Platform
===============================================

Single-input landing page.  The user provides only a part number or
description and clicks Analyze.  The complete pipeline executes
autonomously with no further user interaction required.
"""

from __future__ import annotations

import logging
import time

import streamlit as st

from src.config import get_settings
from src.pipeline.runner import AssessmentPipeline, StageStatus, STAGE_NAMES

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _reset_session() -> None:
    for k in [
        "part_input", "pipeline_result", "nwc_result",
        "research_result", "current_part_id", "current_assessment_id",
    ]:
        st.session_state.pop(k, None)


STAGE_ICONS = {
    StageStatus.PENDING:   "⏳",
    StageStatus.RUNNING:   "⚙️",
    StageStatus.COMPLETED: "✅",
    StageStatus.FAILED:    "⚠️",
    StageStatus.SKIPPED:   "➖",
}


# ── System status banner ───────────────────────────────────────────────────────

def _system_badges() -> None:
    llm_ok   = settings.llm_configured
    search_ok = bool(settings.TAVILY_API_KEY or settings.SERPAPI_KEY)

    badges = []
    if llm_ok:
        badges.append(f"✅ LLM: `{settings.LLM_PROVIDER}/{settings.LLM_MODEL}`")
    else:
        badges.append("⚠️ LLM: **not configured** — set `LLM_API_KEY` in `.env`")

    if settings.TAVILY_API_KEY:
        badges.append("✅ Search: Tavily")
    elif settings.SERPAPI_KEY:
        badges.append("✅ Search: SerpAPI")
    else:
        badges.append("⚠️ Search: DuckDuckGo (may be blocked on corporate networks)")

    st.caption("  •  ".join(badges))


# ── Landing / input screen ─────────────────────────────────────────────────────

def _show_input_form() -> None:
    st.markdown(
        "<h1 style='text-align:center; margin-bottom:0'>🔧</h1>"
        "<h2 style='text-align:center; margin-top:4px'>NWC Spare Part Criticality Assessment</h2>"
        "<p style='text-align:center; color:gray; margin-bottom:32px'>"
        "National Water Company · Saudi Arabia</p>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        with st.form("analyze_form", border=True):
            part_input = st.text_input(
                "Spare Part Number or Description",
                placeholder="e.g.  SS-1F0-3GC  ·  Pump Seal Kit  ·  6SE7021-8TB61",
                label_visibility="visible",
            )
            st.caption(
                "Enter the manufacturer part number, internal code, SAP material number, "
                "or a plain-language description."
            )
            analyze_btn = st.form_submit_button(
                "🔍  Analyze", use_container_width=True, type="primary"
            )
        _system_badges()

    if analyze_btn:
        if not part_input.strip():
            st.warning("Please enter a part number or description.")
        else:
            st.session_state["_pending_input"] = part_input.strip()
            st.rerun()

    # ── Recent assessments ─────────────────────────────────────────────────────
    try:
        from src.agents.database_agent import DatabaseAgent
        recent = DatabaseAgent().list_assessments(limit=5)
        if recent:
            st.markdown("---")
            st.markdown("#### Recent Assessments")
            COLORS = {"Strategic": "🔴", "Very Critical": "🔴",
                      "Semi-Critical": "🟡", "Non-Critical": "🟢",
                      "Critical": "🔴", "Semi Critical": "🟡", "Not Critical": "🟢"}
            for r in recent:
                icon = COLORS.get(r["label"], "⚪")
                col1, col2, col3, col4 = st.columns([3, 3, 2, 2])
                col1.code(r["part_number"][:30])
                col2.caption(r["part_name"] or "—")
                col3.markdown(f"{icon} {r['label']}")
                col4.caption(f"Score: {r['total_score'] or 0:.0f}")
    except Exception:
        pass


# ── Pipeline execution screen ──────────────────────────────────────────────────

def _run_pipeline(part_input: str) -> None:
    st.markdown(
        f"<h3 style='text-align:center'>Analyzing: <code>{part_input[:60]}</code></h3>",
        unsafe_allow_html=True,
    )

    # Pre-create one empty placeholder per stage so they appear before running
    n_stages = len(STAGE_NAMES)
    stage_cells: list = []
    with st.container(border=True):
        cols = st.columns([0.08, 0.55, 0.15, 0.22])
        cols[0].caption("Status")
        cols[1].caption("Stage")
        cols[2].caption("Duration")
        cols[3].caption("Detail")
        st.divider()
        for name in STAGE_NAMES:
            c = st.columns([0.08, 0.55, 0.15, 0.22])
            c[0].markdown(STAGE_ICONS[StageStatus.PENDING])
            c[1].markdown(name)
            c[2].markdown("—")
            c[3].markdown("—")
            # Store mutable placeholders using st.empty()
            row_phs = [st.empty() for _ in range(4)]
            stage_cells.append((row_phs, c))

    progress_bar = st.progress(0.0)
    time_display = st.empty()
    t_global = time.time()

    # ── Progress callback – updates the stage row in-place ────────────────────
    completed_stages = [0]  # mutable counter for closure

    def on_progress(stage_name: str, status: StageStatus, detail: str, data: dict):
        try:
            idx = STAGE_NAMES.index(stage_name)
        except ValueError:
            return

        _, cols_row = stage_cells[idx]
        icon = STAGE_ICONS.get(status, "⏳")
        cols_row[0].markdown(icon)
        cols_row[1].markdown(f"**{stage_name}**" if status == StageStatus.RUNNING else stage_name)
        if status in (StageStatus.COMPLETED, StageStatus.FAILED):
            # duration is filled when stage result is appended
            cols_row[3].caption(detail[:60] if detail else "—")
            completed_stages[0] += 1
            progress_bar.progress(
                completed_stages[0] / n_stages,
                text=f"{completed_stages[0]}/{n_stages} stages complete",
            )
        elapsed = time.time() - t_global
        time_display.caption(f"Elapsed: {elapsed:.1f}s")

    # ── Run pipeline ──────────────────────────────────────────────────────────
    with st.spinner(""):
        pipeline = AssessmentPipeline(on_progress=on_progress)
        result = pipeline.run(part_input)

    # Fill in durations
    for sr in result.stages:
        try:
            idx = STAGE_NAMES.index(sr.name)
            _, cols_row = stage_cells[idx]
            cols_row[2].caption(f"{sr.duration_s:.1f}s")
        except ValueError:
            pass

    total_elapsed = time.time() - t_global
    progress_bar.progress(1.0, text=f"Complete in {total_elapsed:.1f}s")

    # ── Store results ─────────────────────────────────────────────────────────
    if result.success and result.nwc_result:
        st.session_state["pipeline_result"]      = result
        st.session_state["nwc_result"]           = result.nwc_result
        st.session_state["research_result"]      = result.research_result
        st.session_state["current_part_id"]      = result.part_id
        st.session_state["current_assessment_id"] = result.assessment_id
        st.session_state["part_input"]           = part_input

        label = result.nwc_result.label
        score = result.nwc_result.total_score
        LABEL_COLOR = {
            "Strategic": "red", "Very Critical": "red",
            "Semi-Critical": "orange", "Non-Critical": "green",
        }
        color = LABEL_COLOR.get(label, "gray")
        st.success(
            f"Assessment complete — "
            f"**:{color}[{label}]** · Score: {score}/{result.nwc_result.max_score} · "
            f"Confidence: {result.nwc_result.overall_confidence:.0%}"
        )
        st.session_state.pop("_pending_input", None)
        time.sleep(0.8)
        st.switch_page("pages/2_Assessment_Report.py")

    else:
        st.error(
            f"Pipeline failed: {result.error or 'Unknown error'}. "
            "Check your `.env` configuration and try again."
        )
        if st.button("← Try Again"):
            _reset_session()
            st.session_state.pop("_pending_input", None)
            st.rerun()


# ── Main ───────────────────────────────────────────────────────────────────────

if "app_initialized" not in st.session_state:
    try:
        from src.database.connection import init_db
        from src.ingestion.excel_importer import seed_database_if_empty
        init_db()
        seed_database_if_empty()
        st.session_state.app_initialized = True
    except Exception as exc:
        st.error(
            f"**Database unavailable.** Start PostgreSQL first:\n\n"
            f"```\ndocker compose up -d\n```\n\nError: `{exc}`"
        )
        st.stop()

if st.session_state.get("_pending_input"):
    _run_pipeline(st.session_state["_pending_input"])
else:
    _show_input_form()
