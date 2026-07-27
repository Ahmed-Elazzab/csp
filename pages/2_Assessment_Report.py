"""
Assessment Report
=================

Full read-only output of the autonomous NWC criticality assessment.
No user interaction is required or possible on this page.

Sections:
  1. Assessment Summary      — classification banner, score, confidence
  2. Per-Dimension Analysis  — 4 NWC dimensions with AI reasoning + evidence
  3. Research Summary        — collapsible; extracted attributes and sources
  4. LLM Metadata            — model, provider, prompt version, timing
  5. Audit Information       — raw JSON, assessment ID, stage durations
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import streamlit as st

from src.scoring.nwc_engine import MAX_SCORE
from src.utils.helpers import SOURCE_TIER_LABELS

logger = logging.getLogger(__name__)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "nwc_result" not in st.session_state:
    st.warning("No assessment available. Run a new assessment first.")
    if st.button("← Back to Part Lookup"):
        st.switch_page("pages/1_Part_Lookup.py")
    st.stop()

r = st.session_state["nwc_result"]
research  = st.session_state.get("research_result")
part_input = st.session_state.get("part_input", "Unknown Part")
pipeline_result = st.session_state.get("pipeline_result")

# ── Style helpers ──────────────────────────────────────────────────────────────
LABEL_STYLE = {
    "Strategic":     ("#8B0000", "🔴", "#ff000022"),
    "Very Critical": ("#CC0000", "🔴", "#ff000015"),
    "Semi-Critical": ("#CC7700", "🟡", "#ffa50015"),
    "Non-Critical":  ("#1a7a1a", "🟢", "#00800015"),
}

def _style(label: str) -> tuple[str, str, str]:
    return LABEL_STYLE.get(label, ("#555555", "⚪", "#88888815"))

color, icon, bg = _style(r.label)

# ════════════════════════════════════════════════════════════════════════════════
# 1 — Assessment Summary
# ════════════════════════════════════════════════════════════════════════════════

st.markdown(
    f"""<div style="background:{bg}; border-left:8px solid {color};
         padding:24px 28px; border-radius:10px; margin-bottom:24px">
      <div style="font-size:13px; color:#888; margin-bottom:4px">
        NWC Spare Part Criticality Assessment
      </div>
      <div style="font-size:13px; color:#888; margin-bottom:12px">
        Part: <strong>{part_input[:80]}</strong>
      </div>
      <h1 style="color:{color}; margin:0; font-size:2.4rem">{icon} {r.label}</h1>
      <div style="margin-top:8px; font-size:1.1rem; color:#333">
        Score: <strong>{r.total_score} / {MAX_SCORE}</strong>
        &nbsp;·&nbsp;
        Risk: <strong>{r.score_pct:.0f}%</strong>
        &nbsp;·&nbsp;
        AI Confidence: <strong>{r.overall_confidence:.0%}</strong>
      </div>
    </div>""",
    unsafe_allow_html=True,
)

if r.strategic_rules_triggered:
    st.error(
        "**Strategic Override Applied** — One or more deterministic business rules "
        "elevated this part to **Strategic** classification regardless of score.  \n"
        + "  \n".join(f"• {rule}" for rule in r.strategic_rules_triggered)
    )

# Score bar
st.progress(r.score_pct / 100, text=f"Risk Score: {r.score_pct:.0f}% of maximum ({r.total_score}/{MAX_SCORE} pts)")

# Dimension score metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("⚙️ Operations",    f"{r.operations_score}/12",  f"Option {r.operations_option}")
col2.metric("💧 Water Quality", f"{r.water_quality_score}/10", f"Option {r.water_quality_option}")
col3.metric("🔗 Availability",  f"{r.availability_score}/10",  f"Option {r.availability_option}")
col4.metric("🛡️ Safety",        f"{r.safety_score}/10",        f"Option {r.safety_option}")

if r.key_reasons:
    st.markdown("**Key Findings:**")
    for reason in r.key_reasons:
        st.markdown(f"  • {reason}")

# ════════════════════════════════════════════════════════════════════════════════
# 2 — Per-Dimension Analysis
# ════════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("Per-Dimension Engineering Analysis")

DIMS = [
    ("⚙️ Operations Criticality",
     r.operations_option, r.operations_label, r.operations_score,
     r.operations_reason, r.operations_confidence, r.operations_sources, 12),
    ("💧 Water Quality Criticality",
     r.water_quality_option, r.water_quality_label, r.water_quality_score,
     r.water_quality_reason, r.water_quality_confidence, r.water_quality_sources, 10),
    ("🔗 Availability Criticality",
     r.availability_option, r.availability_label, r.availability_score,
     r.availability_reason, r.availability_confidence, r.availability_sources, 10),
    ("🛡️ Safety Criticality",
     r.safety_option, r.safety_label, r.safety_score,
     r.safety_reason, r.safety_confidence, r.safety_sources, 10),
]

for title, opt, lbl, score, reason, conf, srcs, max_s in DIMS:
    conf_color = "green" if conf >= 0.75 else ("orange" if conf >= 0.50 else "red")
    pct = score / max_s * 100

    with st.expander(
        f"{title}  —  Option **{opt}**: {lbl[:60]}  "
        f"({score}/{max_s} pts)  |  Confidence: :{conf_color}[{conf:.0%}]",
        expanded=(conf < 0.6 or score == max_s),
    ):
        st.progress(pct / 100, text=f"{score}/{max_s} pts ({pct:.0f}%)")
        st.markdown(f"**Selected option:** {opt} — *{lbl}*")
        st.markdown(f"**Engineering reasoning:**  \n{reason or 'No reasoning provided.'}")
        if srcs:
            st.markdown("**Supporting evidence:**")
            for s in srcs:
                st.markdown(f"  - {s}")
        if conf < 0.5:
            st.warning(
                f"Low confidence ({conf:.0%}) — the AI had insufficient evidence for this "
                "dimension. The conservative (lowest-risk) option was selected automatically."
            )

# ════════════════════════════════════════════════════════════════════════════════
# 3 — Research Summary (collapsible, read-only)
# ════════════════════════════════════════════════════════════════════════════════

with st.expander("📋 Research Summary", expanded=False):
    st.caption("Automatically extracted from web search and technical documentation. Read-only.")

    if research:
        c1, c2 = st.columns(2)
        c1.markdown(f"**Part Name:** {research.part_name or '—'}")
        c1.markdown(f"**Manufacturer:** {research.manufacturer or '—'}")
        c1.markdown(f"**Model / Part No.:** {research.model_number or '—'}")
        c1.markdown(f"**Part Type:** {research.part_type or '—'}")
        c2.markdown(f"**Country of Origin:** {research.country_of_origin or '—'}")
        c2.markdown(f"**OEM Only:** {research.oem_only}")
        c2.markdown(f"**Substitute Available:** {research.substitute_available}")
        c2.markdown(f"**Obsolescence Risk:** {research.obsolescence_risk or '—'}")

        if research.description:
            st.markdown(f"**Description:** {str(research.description)[:400]}")
        if research.technical_specs:
            specs_text = research.technical_specs if isinstance(research.technical_specs, str) \
                else str(research.technical_specs)
            st.markdown(f"**Technical Specifications:** {specs_text[:400]}")

        st.markdown(f"**Research Confidence:** {research.overall_confidence:.0%}")
        st.markdown(f"**Evidence Sources Found:** {len(research.source_urls)}")

        if research.source_urls:
            st.markdown("**Reference URLs:**")
            for src in research.source_urls[:10]:
                tier_label = SOURCE_TIER_LABELS.get(src.get("tier", 4), "Web")
                title_txt = src.get("title", src.get("url", ""))[:70]
                url = src.get("url", "")
                st.markdown(f"  - [{title_txt}]({url}) — *{tier_label}*")
    else:
        st.info("No research data available.")

# ════════════════════════════════════════════════════════════════════════════════
# 4 — LLM Metadata
# ════════════════════════════════════════════════════════════════════════════════

with st.expander("🤖 LLM Metadata", expanded=False):
    mc1, mc2 = st.columns(2)
    mc1.markdown(f"**Model:** `{r.model_used or '—'}`")
    mc1.markdown(f"**Prompt Version:** `{r.prompt_version or '—'}`")
    mc1.markdown(f"**Overall AI Confidence:** {r.overall_confidence:.1%}")
    mc2.markdown(f"**Assessment ID:** `{st.session_state.get('current_assessment_id', '—')}`")
    if pipeline_result:
        mc2.markdown(f"**Total Processing Time:** `{pipeline_result.total_duration_s:.1f}s`")
        mc2.markdown(f"**Evidence Sources:** `{pipeline_result.evidence_count}`")

# ════════════════════════════════════════════════════════════════════════════════
# 5 — Audit Information
# ════════════════════════════════════════════════════════════════════════════════

with st.expander("🔎 Audit Information", expanded=False):
    st.caption("Full audit trail for this assessment. Stored in the database.")

    ac1, ac2 = st.columns(2)
    ac1.markdown(f"**Assessment ID:** `{st.session_state.get('current_assessment_id', '—')}`")
    ac1.markdown(f"**Part ID:** `{st.session_state.get('current_part_id', '—')}`")
    ac1.markdown(f"**NWC Rule Engine Version:** deterministic · no ML")
    ac2.markdown(f"**Strategic Rules Triggered:** {len(r.strategic_rules_triggered)}")
    ac2.markdown(f"**Total Score:** {r.total_score} / {MAX_SCORE} ({r.score_pct:.0f}%)")

    if pipeline_result:
        st.markdown("**Pipeline Execution Stages:**")
        for sr in pipeline_result.stages:
            icon = "✅" if sr.status.value == "completed" else ("⚠️" if sr.status.value == "failed" else "➖")
            st.markdown(f"  {icon} **{sr.name}** — {sr.duration_s:.2f}s · {sr.detail[:80]}")

    # Raw analysis JSON
    raw_json = st.session_state.get("analysis_json", "")
    if not raw_json:
        try:
            raw_json = r.model_dump_json(indent=2)
        except Exception:
            pass
    if raw_json:
        with st.expander("Raw NWC Analysis JSON (full LLM output)"):
            try:
                st.json(json.loads(raw_json))
            except Exception:
                st.code(raw_json[:2000])

# ── Navigation ─────────────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔍 Assess Another Part", use_container_width=True, type="primary"):
        for k in [
            "part_input", "pipeline_result", "nwc_result",
            "research_result", "current_part_id", "current_assessment_id",
            "_pending_input",
        ]:
            st.session_state.pop(k, None)
        st.switch_page("pages/1_Part_Lookup.py")
with col2:
    st.page_link("pages/3_History.py", label="📜 View Assessment History")
