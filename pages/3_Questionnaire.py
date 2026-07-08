"""
Page 3 – Dynamic Questionnaire

Engine behaviour
────────────────
1. Load the master bank of 30 questions (question_bank.py).
2. Run PrefillEngine to auto-answer questions from research + DB data.
3. Run the relevance engine to rank the remaining unanswered questions.
4. Show only the top-15 most relevant unanswered questions in the form.
5. On submit, merge all prefilled + user answers into SubmittedAnswer objects
   for the scoring engine (Assessment page).

Questions are never hardcoded here – all text comes from the DB (seeded from
Excel).  The master bank provides weights, tags, and prefill mapping only.
"""

from __future__ import annotations

import logging
from collections import defaultdict

import streamlit as st

from src.agents.database_agent import DatabaseAgent
from src.agents.questionnaire_agent import QuestionnaireAgent
from src.questionnaire.prefill_engine import PrefillEngine, PrefilledAnswer
from src.questionnaire.question_bank import (
    QUESTION_BANK,
    QUESTIONS_BY_DB_KEY,
    TOTAL_QUESTIONS,
    QuestionDefinition,
)
from src.questionnaire.relevance_engine import build_part_context, rank_questions_for_part
from src.scoring.engine import score_answer
from src.utils.helpers import QuestionWithContext, SubmittedAnswer

logger = logging.getLogger(__name__)

# ── Guard ──────────────────────────────────────────────────────────────────────
if "current_part_number" not in st.session_state:
    st.warning("No active part. Start from Part Lookup.")
    st.page_link("pages/1_Part_Lookup.py", label="← Back to Part Lookup")
    st.stop()

part_number: str = st.session_state.current_part_number
part_id: int = st.session_state.get("current_part_id", 0)
research_result = st.session_state.get("research_result")

# ── Load DB question text + IDs ────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=600)
def _load_db_question_text() -> dict:
    agent = QuestionnaireAgent()
    qs = agent.load_questions()
    return {(q.scenario, q.question_id): q.question_text for q in qs}


@st.cache_data(show_spinner=False, ttl=600)
def _load_db_question_ids() -> dict:
    return QuestionnaireAgent().get_question_db_ids()


db_text: dict = _load_db_question_text()
db_ids: dict = _load_db_question_ids()


def _qtext(q: QuestionDefinition) -> str:
    """Return DB text when available, otherwise bank fallback."""
    return db_text.get((q.scenario, q.question_id), q.question_text)


# ── Prefill engine ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Analysing part data...", ttl=120)
def _compute_prefills(part_number: str, part_id: int, _research_result):
    db_agent = DatabaseAgent()
    db_attrs = db_agent.get_part_attributes(part_id) if part_id else {}
    return PrefillEngine().compute_prefills(
        research_result=_research_result,
        db_attributes=db_attrs,
    )


try:
    prefills: list[PrefilledAnswer] = _compute_prefills(
        part_number, part_id, research_result
    )
except Exception as exc:
    logger.exception("Prefill engine error")
    st.error(f"Prefill engine failed: {exc}")
    prefills = []

prefilled_ids: set[str] = {p.question_id for p in prefills}
prefill_map: dict[str, PrefilledAnswer] = {p.question_id: p for p in prefills}

# ── Relevance engine ───────────────────────────────────────────────────────────
_db_agent = DatabaseAgent()
_db_attrs = _db_agent.get_part_attributes(part_id) if part_id else {}
part_context = build_part_context(research_result, _db_attrs, prefills)

visible_questions: list[QuestionDefinition] = rank_questions_for_part(
    prefilled_ids=prefilled_ids,
    part_context=part_context,
    max_questions=15,
)

n_prefilled = len(prefilled_ids)
n_visible = len(visible_questions)


# ── Helper: finalise answers and navigate ─────────────────────────────────────
def _finalize(user_selections: dict) -> None:
    """Merge prefilled + user answers, store in session state, navigate."""
    submitted_answers: list[SubmittedAnswer] = []
    questionnaire_data: list[QuestionWithContext] = []

    for q in QUESTION_BANK:
        q_key = f"{q.scenario}|{q.question_id}"
        db_id = db_ids.get((q.scenario, q.question_id), 0)
        opts = q.answer_options
        qt = _qtext(q)

        pf = prefill_map.get(q.id)
        user_val = user_selections.get(q_key)

        if user_val:
            a_score = score_answer(q.scenario, q.question_id, user_val)
            submitted_answers.append(
                SubmittedAnswer(
                    question_db_id=db_id,
                    scenario=q.scenario,
                    question_id=q.question_id,
                    answer_value=user_val,
                    answer_score=a_score,
                    answered_by="user",
                    confidence=1.0,
                    source="User",
                )
            )
            pre_val, conf, src, a_score_q = user_val, 1.0, "User", a_score
            needs_input = False
        elif pf:
            submitted_answers.append(pf.to_submitted_answer(db_id))
            pre_val, conf, src, a_score_q = (
                pf.answer_value, pf.confidence, pf.source_detail, pf.answer_score
            )
            needs_input = False
        else:
            pre_val, conf, src, a_score_q = None, 0.0, "user", 0.0
            needs_input = True

        questionnaire_data.append(
            QuestionWithContext(
                db_id=db_id,
                scenario=q.scenario,
                question_id=q.question_id,
                question_text=qt,
                answer_options=opts,
                pre_filled_answer=pre_val,
                pre_filled_score=a_score_q,
                confidence=conf,
                source=src,
                requires_user_input=needs_input,
            )
        )

    st.session_state.submitted_answers = submitted_answers
    st.session_state.questionnaire_data = questionnaire_data
    st.session_state.user_answers = user_selections
    st.session_state.pop("assessment_result", None)
    st.session_state.pop("current_assessment_id", None)

    st.success("Answers saved - redirecting to Assessment Result...")
    st.switch_page("pages/4_Assessment_Result.py")


# ── Page header ────────────────────────────────────────────────────────────────
st.title("Criticality Questionnaire")
st.markdown(f"**Part:** `{part_number}`")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total questions", TOTAL_QUESTIONS)
col2.metric("Auto-filled", n_prefilled, help="Answered from research / DB data")
col3.metric("Unanswered", TOTAL_QUESTIONS - n_prefilled)
col4.metric("Showing", n_visible, help="Top most-relevant unanswered questions")

st.caption(
    "Questions already answered from research data are hidden. "
    "Only the most relevant unanswered questions are shown in the form."
)

# ── Auto-filled answers (collapsed) ───────────────────────────────────────────
if prefills:
    with st.expander(
        f"{n_prefilled} auto-filled answers (click to review)", expanded=False
    ):
        st.caption(
            "These answers were derived from research, OEM data, or previous inputs."
        )
        for p in sorted(prefills, key=lambda x: x.scenario):
            q_def = QUESTIONS_BY_DB_KEY.get((p.scenario, p.db_question_id))
            q_label = _qtext(q_def) if q_def else p.db_question_id
            opts = q_def.answer_options if q_def else []
            human_label = next(
                (o.label for o in opts if o.value == p.answer_value), p.answer_value
            )
            conf_color = (
                "green"
                if p.confidence >= 0.8
                else ("orange" if p.confidence >= 0.5 else "red")
            )
            st.markdown(
                f"- **{q_label}**  \n"
                f"  Answer: *{human_label}* "
                f"| Source: `{p.source_detail}` "
                f"| Confidence: :{conf_color}[{p.confidence:.0%}] "
                f"| Score: `{p.answer_score:.0f}/100`"
            )

# ── Questionnaire form ─────────────────────────────────────────────────────────
st.markdown("---")

if not visible_questions:
    st.success(
        "All questions have been auto-filled from available data! "
        "Click below to calculate the criticality score."
    )
    if st.button(
        "Calculate Criticality Score", use_container_width=True, type="primary"
    ):
        _finalize({})

else:
    st.subheader(f"Answer the {n_visible} most relevant questions")
    st.caption(
        "These are the highest-priority questions that could not be answered "
        "automatically. They are grouped by risk category."
    )

    scenario_groups: dict = defaultdict(list)
    for q in visible_questions:
        scenario_groups[q.scenario].append(q)

    with st.form("questionnaire_form"):
        for scenario, qs_in_scenario in scenario_groups.items():
            st.subheader(scenario)
            for q in qs_in_scenario:
                opts = q.answer_options
                if not opts:
                    continue
                st.radio(
                    f"**{q.question_id}. {_qtext(q)}**",
                    options=[o.label for o in opts],
                    index=0,
                    key=f"q_{q.scenario}|{q.question_id}",
                )
            st.markdown("---")

        submitted = st.form_submit_button(
            "Calculate Criticality Score",
            use_container_width=True,
            type="primary",
        )

    if submitted:
        user_selections: dict = {}
        for q in visible_questions:
            widget_key = f"q_{q.scenario}|{q.question_id}"
            chosen_label = st.session_state.get(widget_key)
            if chosen_label:
                val = next(
                    (o.value for o in q.answer_options if o.label == chosen_label),
                    None,
                )
                if val:
                    user_selections[f"{q.scenario}|{q.question_id}"] = val
        _finalize(user_selections)

# ── Navigation ─────────────────────────────────────────────────────────────────
st.markdown("---")
col1, _ = st.columns([1, 3])
with col1:
    st.page_link("pages/2_Research_Results.py", label="Back to Research Results")
