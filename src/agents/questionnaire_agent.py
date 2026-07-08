"""
Questionnaire Agent – loads questions from DB and pre-fills answers from research.

Logic:
1. Load all questions from the questionnaire_questions table (seeded from Excel).
2. For each question, check if the corresponding attribute was extracted during
   research with confidence ≥ threshold.
3. If yes → mark as pre-filled (answered_by="research"), still show to user for
   confirmation but indicate the source.
4. If no → mark as requiring user input.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.config import get_settings
from src.database.connection import get_db_session
from src.database.models import QuestionnaireQuestion
from src.scoring.engine import SCORING_RUBRICS, get_answer_options, score_answer
from src.utils.helpers import (
    AnswerOption,
    AttributeData,
    QuestionWithContext,
    ResearchResult,
    SubmittedAnswer,
)

logger = logging.getLogger(__name__)

# ── Mapping: (scenario, question_id) → normalised attribute name ──────────────
# The attribute name must match the key used in ResearchResult.attributes
QUESTION_TO_ATTRIBUTE: dict[tuple[str, str], str] = {
    ("Scenario 1 - Operations Criticality", "Q1"): "operational_shutdown_impact",
    ("Scenario 1 - Operations Criticality", "Q2"): "redundancy_backup_equipment_available",
    ("Scenario 1 - Operations Criticality", "Q5"): "single_point_of_failure_flag",
    ("Scenario 1 - Operations Criticality", "Q9"): "calibration_commissioning_requirement",
    ("Scenario 1 - Operations Criticality", "Q10"): "repairability_flag",
    ("Scenario 2 - Supply Chain Risk", "Q1"): "procurement_lead_time",
    ("Scenario 2 - Supply Chain Risk", "Q2"): "lead_time_variability",
    ("Scenario 2 - Supply Chain Risk", "Q3"): "supplier_count",
    ("Scenario 2 - Supply Chain Risk", "Q4"): "oem_only_requirement",
    ("Scenario 2 - Supply Chain Risk", "Q5"): "approved_substitute_availability",
    ("Scenario 2 - Supply Chain Risk", "Q6"): "supplier_reliability_otif",
    ("Scenario 2 - Supply Chain Risk", "Q7"): "local_presence_distributor_availability",
    ("Scenario 2 - Supply Chain Risk", "Q8"): "country_of_origin_concentration",
    ("Scenario 2 - Supply Chain Risk", "Q10"): "obsolescence_risk",
    ("Scenario 3 - Inventory & Financial", "Q1"): "stock_on_hand_quantity",
    ("Scenario 3 - Inventory & Financial", "Q2"): "monthly_consumption_rate",
    ("Scenario 3 - Inventory & Financial", "Q3"): "consumption_in_last_12_months",
    ("Scenario 3 - Inventory & Financial", "Q4"): "stockout_history",
    ("Scenario 3 - Inventory & Financial", "Q5"): "unit_purchase_cost",
    ("Scenario 3 - Inventory & Financial", "Q9"): "consumption_in_last_36_months",
}

# ── Value-to-answer-option heuristic mapping ───────────────────────────────────
# Maps raw attribute values (from research) to answer option value-keys
ATTRIBUTE_VALUE_MAP: dict[str, dict[str, str]] = {
    "oem_only_requirement": {"true": "yes_oem", "false": "no_oem"},
    "approved_substitute_availability": {"true": "approved_sub", "false": "no_substitute"},
    "redundancy_backup_equipment_available": {"true": "full_backup", "false": "no_backup"},
    "single_point_of_failure_flag": {"true": "yes_spof", "false": "no_spof"},
    "repairability_flag": {"true": "repairable", "false": "replace_short"},
    "calibration_commissioning_requirement": {"true": "yes_minor", "false": "no_calibration"},
    "obsolescence_risk": {
        "high": "high_obs",
        "medium": "medium_obs",
        "low": "low_obs",
    },
    "lead_time_variability": {
        "high": "high_var",
        "medium": "medium_var",
        "low": "low_var",
    },
    "local_presence_distributor_availability": {
        "true": "local_available",
        "false": "no_local",
        "local": "local_available",
    },
}


class QuestionnaireAgent:
    """Prepares adaptive questionnaire, pre-filling from research where possible."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def load_questions(self) -> list[QuestionnaireQuestion]:
        """Load all questions from DB ordered by scenario then question_id."""
        with get_db_session() as session:
            qs = (
                session.query(QuestionnaireQuestion)
                .order_by(
                    QuestionnaireQuestion.scenario,
                    QuestionnaireQuestion.question_id,
                )
                .all()
            )
            # Detach from session
            session.expunge_all()
            return qs

    def get_question_db_ids(self) -> dict[tuple[str, str], int]:
        """Return {(scenario, question_id): db_id} mapping."""
        qs = self.load_questions()
        return {(q.scenario, q.question_id): q.id for q in qs}

    def prepare_questionnaire(
        self, research_result: Optional[ResearchResult] = None
    ) -> list[QuestionWithContext]:
        """
        Build the full questionnaire with pre-fills from research.

        Questions where research confidence ≥ CONFIDENCE_THRESHOLD are marked
        requires_user_input=False (shown to user as "pre-filled" confirmations).
        """
        questions = self.load_questions()
        threshold = self.settings.CONFIDENCE_THRESHOLD
        result: list[QuestionWithContext] = []

        for q in questions:
            options = get_answer_options(q.scenario, q.question_id)
            if not options:
                logger.debug("No rubric for (%s, %s) – skipping", q.scenario, q.question_id)
                continue

            pre_value, pre_score, confidence, source, requires_input = (
                self._try_prefill(q.scenario, q.question_id, research_result, threshold)
            )

            result.append(
                QuestionWithContext(
                    db_id=q.id,
                    scenario=q.scenario,
                    question_id=q.question_id,
                    question_text=q.question_text,
                    answer_options=options,
                    pre_filled_answer=pre_value,
                    pre_filled_score=pre_score,
                    confidence=confidence,
                    source=source,
                    requires_user_input=requires_input,
                )
            )

        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _try_prefill(
        self,
        scenario: str,
        qid: str,
        research: Optional[ResearchResult],
        threshold: float,
    ) -> tuple[Optional[str], float, float, str, bool]:
        """
        Attempt to pre-fill an answer from research data.

        Returns (answer_value, score, confidence, source, requires_user_input).
        """
        if research is None:
            return None, 0.0, 0.0, "user", True

        attr_name = QUESTION_TO_ATTRIBUTE.get((scenario, qid))
        if attr_name is None:
            return None, 0.0, 0.0, "user", True

        attr_data: Optional[AttributeData] = research.attributes.get(attr_name)
        if attr_data is None:
            return None, 0.0, 0.0, "user", True

        # Map raw value to an answer option key
        answer_key = self._map_value_to_option(attr_name, attr_data.value, scenario, qid)
        if answer_key is None:
            return None, 0.0, attr_data.confidence, "research", True

        score = score_answer(scenario, qid, answer_key)
        requires_input = attr_data.confidence < threshold

        source_label = f"Research ({attr_data.source})" if attr_data.source else "Research"
        return answer_key, score, attr_data.confidence, source_label, requires_input

    def _map_value_to_option(
        self, attr_name: str, raw_value: str, scenario: str, qid: str
    ) -> Optional[str]:
        """Map a raw attribute value string to an answer option value-key."""
        val = raw_value.strip().lower()

        # Use explicit mapping table if available
        mapping = ATTRIBUTE_VALUE_MAP.get(attr_name)
        if mapping:
            return mapping.get(val)

        # Direct match against option values or labels
        options = get_answer_options(scenario, qid)
        for opt in options:
            if val == opt.value.lower() or val == opt.label.lower():
                return opt.value

        return None

    def build_submitted_answers(
        self,
        questionnaire: list[QuestionWithContext],
        user_selections: dict[str, str],  # key = f"{scenario}|{qid}", value = answer_value
    ) -> list[SubmittedAnswer]:
        """
        Merge user selections with pre-fills to produce the final answer list.

        User selections always override pre-filled values.
        """
        answers: list[SubmittedAnswer] = []
        for q in questionnaire:
            key = f"{q.scenario}|{q.question_id}"
            chosen_value = user_selections.get(key) or q.pre_filled_answer

            if chosen_value is None:
                continue

            score = score_answer(q.scenario, q.question_id, chosen_value)
            answered_by = "user" if key in user_selections else "research"

            answers.append(
                SubmittedAnswer(
                    question_db_id=q.db_id,
                    scenario=q.scenario,
                    question_id=q.question_id,
                    answer_value=chosen_value,
                    answer_score=score,
                    answered_by=answered_by,
                    confidence=1.0 if answered_by == "user" else q.confidence,
                    source=q.source if answered_by == "research" else "User",
                )
            )
        return answers
