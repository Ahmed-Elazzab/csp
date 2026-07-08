"""
Database Agent – persists part data, attributes, research sources, and assessments.

All write operations use upsert semantics so the agent is safe to call multiple times.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.database.connection import get_db_session
from src.database.models import (
    Assessment,
    PartAttribute,
    QuestionnaireAnswer,
    ResearchSource,
    SparePart,
)
from src.utils.helpers import AssessmentResult, ResearchResult, SubmittedAnswer

logger = logging.getLogger(__name__)


class DatabaseAgent:
    """Handles all database read/write operations for the assessment workflow."""

    # ── Part master ───────────────────────────────────────────────────────────

    def upsert_part(self, result: ResearchResult) -> int:
        """Create or update a SparePart record. Returns the part DB id."""
        with get_db_session() as session:
            part = (
                session.query(SparePart)
                .filter_by(part_number=result.part_number)
                .first()
            )
            if part is None:
                part = SparePart(part_number=result.part_number)
                session.add(part)
                session.flush()  # get id before commit

            part.part_name = result.part_name or part.part_name
            part.description = result.description or part.description
            part.manufacturer = result.manufacturer or part.manufacturer
            part.model_number = result.model_number or part.model_number
            part.part_type = result.part_type or part.part_type
            part.technical_specs = result.technical_specs or part.technical_specs
            part.country_of_origin = result.country_of_origin or part.country_of_origin
            if result.oem_only is not None:
                part.oem_only = result.oem_only
            if result.substitute_available is not None:
                part.substitute_available = result.substitute_available
            part.obsolescence_risk = result.obsolescence_risk or part.obsolescence_risk

            session.flush()
            part_id = part.id

        logger.info("Part upserted: id=%d, number=%s", part_id, result.part_number)
        return part_id

    def save_part_attributes(self, part_id: int, result: ResearchResult) -> int:
        """Upsert extracted attributes for a part. Returns count saved."""
        saved = 0
        with get_db_session() as session:
            for attr_name, attr_data in result.attributes.items():
                existing = (
                    session.query(PartAttribute)
                    .filter_by(part_id=part_id, attribute_name=attr_name)
                    .first()
                )
                # Only overwrite if new data has higher confidence or better tier
                if existing:
                    if (
                        attr_data.confidence >= existing.confidence_level
                        or attr_data.source_tier < existing.source_tier
                    ):
                        existing.attribute_value = attr_data.value
                        existing.source = attr_data.source
                        existing.source_url = attr_data.source_url
                        existing.confidence_level = attr_data.confidence
                        existing.source_tier = attr_data.source_tier
                else:
                    session.add(
                        PartAttribute(
                            part_id=part_id,
                            attribute_name=attr_name,
                            attribute_value=attr_data.value,
                            source=attr_data.source,
                            source_url=attr_data.source_url,
                            confidence_level=attr_data.confidence,
                            source_tier=attr_data.source_tier,
                        )
                    )
                    saved += 1
        return saved

    def save_research_sources(self, part_id: int, result: ResearchResult) -> None:
        """Persist web search source URLs (deduplicated by URL)."""
        with get_db_session() as session:
            existing_urls: set[str] = {
                r.url
                for r in session.query(ResearchSource)
                .filter_by(part_id=part_id)
                .all()
            }
            for src in result.source_urls:
                url = src.get("url", "")
                if url and url not in existing_urls:
                    session.add(
                        ResearchSource(
                            part_id=part_id,
                            url=url,
                            title=src.get("title"),
                            snippet=src.get("snippet"),
                            reliability_tier=src.get("tier", 4),
                        )
                    )
                    existing_urls.add(url)

    def save_manual_attribute(
        self,
        part_id: int,
        attribute_name: str,
        value: str,
        source: str = "User / Manual Input",
        confidence: float = 1.0,
        source_tier: int = 1,
    ) -> None:
        """Save or overwrite a single attribute entered manually by the user."""
        with get_db_session() as session:
            existing = (
                session.query(PartAttribute)
                .filter_by(part_id=part_id, attribute_name=attribute_name)
                .first()
            )
            if existing:
                existing.attribute_value = value
                existing.source = source
                existing.confidence_level = confidence
                existing.source_tier = source_tier
                existing.source_url = None
            else:
                session.add(
                    PartAttribute(
                        part_id=part_id,
                        attribute_name=attribute_name,
                        attribute_value=value,
                        source=source,
                        confidence_level=confidence,
                        source_tier=source_tier,
                    )
                )

    # ── Part retrieval ────────────────────────────────────────────────────────

    def get_part_by_number(self, part_number: str) -> Optional[SparePart]:
        with get_db_session() as session:
            part = (
                session.query(SparePart).filter_by(part_number=part_number).first()
            )
            if part:
                # Eagerly load relations while session is open
                _ = part.attributes
                _ = part.research_sources
                _ = part.assessments
            return part

    def get_part_attributes(self, part_id: int) -> dict[str, dict]:
        """Return {attribute_name: {value, confidence, source, tier}} dict."""
        with get_db_session() as session:
            attrs = (
                session.query(PartAttribute).filter_by(part_id=part_id).all()
            )
            return {
                a.attribute_name: {
                    "value": a.attribute_value,
                    "confidence": a.confidence_level,
                    "source": a.source,
                    "source_url": a.source_url,
                    "source_tier": a.source_tier,
                }
                for a in attrs
            }

    def get_research_sources(self, part_id: int) -> list[dict]:
        with get_db_session() as session:
            srcs = (
                session.query(ResearchSource).filter_by(part_id=part_id).all()
            )
            return [
                {
                    "url": s.url,
                    "title": s.title,
                    "snippet": s.snippet,
                    "tier": s.reliability_tier,
                }
                for s in srcs
            ]

    # ── Assessment ────────────────────────────────────────────────────────────

    def create_assessment(
        self,
        part_id: int,
        result: AssessmentResult,
        answers: list[SubmittedAnswer],
        question_db_ids: dict[tuple[str, str], int],
    ) -> int:
        """Persist a complete assessment with all answers. Returns assessment id."""
        with get_db_session() as session:
            assessment = Assessment(
                part_id=part_id,
                operations_score=result.operations_score,
                supply_chain_score=result.supply_chain_score,
                inventory_score=result.inventory_score,
                total_score=result.total_score,
                label=result.label,
                key_reasons=json.dumps(result.key_reasons),
                override_rules_triggered=json.dumps(result.override_rules_triggered),
                missing_attributes=json.dumps(result.missing_attributes),
            )
            session.add(assessment)
            session.flush()

            for ans in answers:
                q_db_id = question_db_ids.get((ans.scenario, ans.question_id))
                if q_db_id is None:
                    continue
                session.add(
                    QuestionnaireAnswer(
                        assessment_id=assessment.id,
                        question_db_id=q_db_id,
                        answer_value=ans.answer_value,
                        answer_score=ans.answer_score,
                        answered_by=ans.answered_by,
                        confidence=ans.confidence,
                        source=ans.source,
                    )
                )

            session.flush()
            assessment_id = assessment.id

        logger.info(
            "Assessment saved: id=%d, label=%s, score=%.1f",
            assessment_id,
            result.label,
            result.total_score,
        )
        return assessment_id

    def confirm_assessment(
        self,
        assessment_id: int,
        confirmed: bool,
        override_label: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> None:
        """Mark an assessment as user-confirmed and optionally override the label."""
        with get_db_session() as session:
            a = session.query(Assessment).filter_by(id=assessment_id).first()
            if a:
                a.confirmed_by_user = confirmed
                if override_label:
                    a.override_label = override_label
                    a.override_reason = override_reason

    def get_assessment(self, assessment_id: int) -> Optional[Assessment]:
        with get_db_session() as session:
            a = session.query(Assessment).filter_by(id=assessment_id).first()
            if a:
                _ = a.part
                _ = a.answers
            return a

    # ── History ───────────────────────────────────────────────────────────────

    def list_assessments(self, limit: int = 100) -> list[dict]:
        """Return recent assessments as plain dicts for display in history page."""
        with get_db_session() as session:
            rows = (
                session.query(Assessment, SparePart)
                .join(SparePart, Assessment.part_id == SparePart.id)
                .order_by(Assessment.created_at.desc())
                .limit(limit)
                .all()
            )
            result = []
            for asm, part in rows:
                final_label = asm.override_label or asm.label
                result.append(
                    {
                        "id": asm.id,
                        "part_number": part.part_number,
                        "part_name": part.part_name,
                        "label": final_label,
                        "total_score": asm.total_score,
                        "ops_score": asm.operations_score,
                        "sc_score": asm.supply_chain_score,
                        "inv_score": asm.inventory_score,
                        "confirmed": asm.confirmed_by_user,
                        "created_at": asm.created_at,
                    }
                )
            return result
