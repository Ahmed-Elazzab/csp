"""
Page 4 – Assessment Result: final label, scores, breakdown, and user override.
"""

from __future__ import annotations

import json
import logging

import streamlit as st

from src.agents.criticality_agent import CriticalityAgent
from src.agents.database_agent import DatabaseAgent
from src.agents.questionnaire_agent import QuestionnaireAgent
from src.scoring.engine import SCENARIO_INV, SCENARIO_OPS, SCENARIO_SC
from src.utils.helpers import SOURCE_TIER_LABELS

logger = logging.getLogger(__name__)

st.title("🎯 Assessment Result")

# ── Guards ────────────────────────────────────────────────────────────────────
if "current_part_number" not in st.session_state:
    st.warning("No active assessment. Start from Part Lookup.")
    st.page_link("pages/1_Part_Lookup.py", label="← Back to Part Lookup")
    st.stop()

if "submitted_answers" not in st.session_state:
    st.warning("No answers found. Complete the questionnaire first.")
    st.page_link("pages/3_Questionnaire.py", label="← Back to Questionnaire")
    st.stop()

part_number = st.session_state.current_part_number
part_id: int = st.session_state.get("current_part_id", 0)
submitted_answers = st.session_state.submitted_answers
questionnaire = st.session_state.get("questionnaire_data", [])

# ── Run scoring if not already done ───────────────────────────────────────────
if "assessment_result" not in st.session_state:
    with st.spinner("Calculating criticality score…"):
        try:
            q_agent = QuestionnaireAgent()
            q_db_ids = q_agent.get_question_db_ids()

            crit_agent = CriticalityAgent()
            result, assessment_id = crit_agent.assess(
                submitted_answers=submitted_answers,
                part_id=part_id,
                question_db_ids=q_db_ids,
            )
            st.session_state.assessment_result = result
            st.session_state.current_assessment_id = assessment_id
        except Exception as exc:
            logger.exception("Assessment failed")
            st.error(f"Assessment calculation failed: {exc}")
            st.stop()

result = st.session_state.assessment_result
assessment_id: int = st.session_state.get("current_assessment_id", 0)


# ── Helper: colour by label ────────────────────────────────────────────────────
def label_style(label: str) -> tuple[str, str]:
    if label == "Critical":
        return "🔴", "#FF4B4B"
    if label == "Semi Critical":
        return "🟡", "#FFA500"
    return "🟢", "#2ECC71"


icon, color = label_style(result.label)

# ── Final verdict ──────────────────────────────────────────────────────────────
st.markdown(
    f"""
    <div style="background-color:{color}22; border-left: 6px solid {color};
         padding: 20px; border-radius: 8px; margin-bottom: 20px;">
      <h1 style="color:{color}; margin:0">{icon} {result.label}</h1>
      <h2 style="margin:4px 0">Total Score: {result.total_score:.1f} / 100</h2>
      <p style="margin:0">Part: <strong>{part_number}</strong></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── Score breakdown ────────────────────────────────────────────────────────────
st.subheader("📊 Score Breakdown")

col1, col2, col3 = st.columns(3)
col1.metric(
    "⚙️ Operations Criticality",
    f"{result.operations_score:.1f} / 100",
    delta=f"Weight: 45%",
)
col2.metric(
    "🚢 Supply Chain Risk",
    f"{result.supply_chain_score:.1f} / 100",
    delta=f"Weight: 35%",
)
col3.metric(
    "📦 Inventory & Financial",
    f"{result.inventory_score:.1f} / 100",
    delta=f"Weight: 20%",
)

# Visual progress bars
st.markdown("**Risk scores (higher = more critical):**")
st.progress(result.operations_score / 100, text=f"Operations: {result.operations_score:.0f}%")
st.progress(result.supply_chain_score / 100, text=f"Supply Chain: {result.supply_chain_score:.0f}%")
st.progress(result.inventory_score / 100, text=f"Inventory: {result.inventory_score:.0f}%")

# ── Key reasons ───────────────────────────────────────────────────────────────
if result.key_reasons:
    st.subheader("🔑 Key Reasons")
    for reason in result.key_reasons:
        st.markdown(f"- {reason}")

# ── Override rules ─────────────────────────────────────────────────────────────
if result.override_rules_triggered:
    st.subheader("⚡ Override Rules Applied")
    rule_descriptions = {
        "complete_shutdown_no_backup": "Complete shutdown + no backup → forced Critical",
        "spof_long_lead_time": "Single point of failure + long lead time → forced Critical",
        "sole_source_no_sub_no_stock": "Single supplier + no substitute + no/low stock → forced Critical",
        "partial_impact_high_supply_risk": "Partial impact + high supply risk → confirmed Semi Critical",
        "no_impact_good_supply": "No operational impact + excellent supply chain → forced Not Critical",
    }
    for rule in result.override_rules_triggered:
        st.warning(f"⚡ {rule_descriptions.get(rule, rule)}")

# ── Missing / low-confidence ───────────────────────────────────────────────────
with st.expander("⚠️ Missing & Low-Confidence Data"):
    if result.missing_attributes:
        st.markdown("**Unanswered questions (defaulted to moderate risk):**")
        for attr in result.missing_attributes:
            st.markdown(f"- `{attr}`")
    if result.low_confidence_attributes:
        st.markdown("**Low-confidence answers from research:**")
        for attr in result.low_confidence_attributes:
            st.markdown(f"- `{attr}`")
    if not result.missing_attributes and not result.low_confidence_attributes:
        st.success("All questions answered with good confidence.")

# ── Per-question detail ───────────────────────────────────────────────────────
with st.expander("🔍 Per-Question Score Detail"):
    for scenario in (SCENARIO_OPS, SCENARIO_SC, SCENARIO_INV):
        st.markdown(f"**{scenario}**")
        qs_answers = {
            (a.scenario, a.question_id): a for a in submitted_answers
        }
        scenario_qs = [q for q in questionnaire if q.scenario == scenario]
        for q in scenario_qs:
            ans = qs_answers.get((q.scenario, q.question_id))
            score_val = result.per_question_scores.get(f"{q.scenario}|{q.question_id}", "—")
            answered_by = ans.answered_by if ans else "—"
            answer_label = "—"
            if ans:
                # Find human-readable label
                for opt in q.answer_options:
                    if opt.value == ans.answer_value:
                        answer_label = opt.label
                        break
            st.markdown(
                f"  - **{q.question_id}**: {q.question_text[:60]}…  \n"
                f"    Answer: *{answer_label}* | Score: **{score_val}** | Source: `{answered_by}`"
            )

# ── Source URLs ────────────────────────────────────────────────────────────────
research_result = st.session_state.get("research_result")
if research_result and research_result.source_urls:
    with st.expander("🔗 Research Sources Used"):
        for src in research_result.source_urls:
            tier_label = SOURCE_TIER_LABELS.get(src.get("tier", 4), "Web")
            st.markdown(f"- [{src.get('title', src.get('url', ''))}]({src.get('url', '')}) — *{tier_label}*")

# ── User confirmation / override ───────────────────────────────────────────────
st.markdown("---")
st.subheader("✅ Confirm or Override")
st.caption(
    "Review the AI-proposed classification above and confirm it, or select a different label "
    "with justification. Your decision will be stored in the database."
)

with st.form("confirm_form"):
    override_option = st.radio(
        "Final Classification",
        options=[
            f"✅ Accept: **{result.label}** (proposed by system)",
            "🔴 Override → Critical",
            "🟡 Override → Semi Critical",
            "🟢 Override → Not Critical",
        ],
        index=0,
    )
    override_reason_text = st.text_area(
        "Override Reason (required if overriding)",
        placeholder="e.g. Engineering team confirmed this part has a backup unit.",
        height=80,
    )
    confirm_btn = st.form_submit_button(
        "💾 Confirm & Save Assessment", use_container_width=True, type="primary"
    )

if confirm_btn:
    override_map = {
        f"✅ Accept: **{result.label}** (proposed by system)": None,
        "🔴 Override → Critical": "Critical",
        "🟡 Override → Semi Critical": "Semi Critical",
        "🟢 Override → Not Critical": "Not Critical",
    }
    override_label = override_map.get(override_option)

    if override_label and not override_reason_text.strip():
        st.warning("Please provide a reason when overriding the system classification.")
    else:
        try:
            crit_agent = CriticalityAgent()
            crit_agent.confirm(
                assessment_id=assessment_id,
                override_label=override_label,
                override_reason=override_reason_text.strip() or None,
            )
            final = override_label or result.label
            fi, fc = label_style(final)
            st.success(f"{fi} Assessment confirmed: **{final}**")
        except Exception as exc:
            st.error(f"Save failed: {exc}")

# ── Navigation ─────────────────────────────────────────────────────────────────
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.page_link("pages/3_Questionnaire.py", label="← Back to Questionnaire")
with col2:
    st.page_link("pages/5_History.py", label="📜 View History")
with col3:
    if st.button("🔄 Assess Another Part", use_container_width=True):
        for k in [
            "current_part_number", "current_part_id", "research_result",
            "questionnaire_data", "user_answers", "current_assessment_id",
            "assessment_result", "submitted_answers",
        ]:
            st.session_state.pop(k, None)
        st.switch_page("pages/1_Part_Lookup.py")
