"""
Criticality Agent – thin wrapper around the scoring engine.

Separates the engine (pure functions) from the agent (orchestration + DB save).
"""

from __future__ import annotations

import logging
from typing import Optional

from src.agents.database_agent import DatabaseAgent
from src.scoring.engine import calculate_assessment
from src.utils.helpers import AssessmentResult, ResearchResult, SubmittedAnswer

logger = logging.getLogger(__name__)


class CriticalityAgent:
    """Calculates criticality and persists the assessment."""

    def __init__(self, db_agent: Optional[DatabaseAgent] = None) -> None:
        self.db_agent = db_agent or DatabaseAgent()

    def assess(
        self,
        submitted_answers: list[SubmittedAnswer],
        part_id: int,
        question_db_ids: dict[tuple[str, str], int],
    ) -> tuple[AssessmentResult, int]:
        """
        Run the scoring engine and save the result.

        Returns (AssessmentResult, assessment_db_id).
        """
        result = calculate_assessment(submitted_answers)

        assessment_id = self.db_agent.create_assessment(
            part_id=part_id,
            result=result,
            answers=submitted_answers,
            question_db_ids=question_db_ids,
        )

        logger.info(
            "Assessment complete: part_id=%d, label=%s, score=%.1f",
            part_id,
            result.label,
            result.total_score,
        )
        return result, assessment_id

    def confirm(
        self,
        assessment_id: int,
        override_label: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> None:
        """Confirm an assessment (with optional user override)."""
        self.db_agent.confirm_assessment(
            assessment_id=assessment_id,
            confirmed=True,
            override_label=override_label,
            override_reason=override_reason,
        )
        logger.info(
            "Assessment %d confirmed (override=%s)",
            assessment_id,
            override_label,
        )
