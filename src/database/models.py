"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AttributeDefinition(Base):
    """Reference – loaded from Excel 'Attributes' sheet."""

    __tablename__ = "attribute_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    impact: Mapped[Optional[str]] = mapped_column(String(50))
    reasons: Mapped[Optional[str]] = mapped_column(Text)
    data_type: Mapped[Optional[str]] = mapped_column(String(50))
    sample_values: Mapped[Optional[str]] = mapped_column(Text)
    attribute_source: Mapped[Optional[str]] = mapped_column(String(255))
    currently_exists: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class QuestionnaireQuestion(Base):
    """Reference – loaded from Excel 'Scenario Questions' sheet."""

    __tablename__ = "questionnaire_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False)
    question_id: Mapped[str] = mapped_column(String(10), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("scenario", "question_id"),)

    answers: Mapped[list[QuestionnaireAnswer]] = relationship(
        "QuestionnaireAnswer", back_populates="question"
    )


class SparePart(Base):
    """Core spare-part master record."""

    __tablename__ = "spare_parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_number: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, index=True
    )
    part_name: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255))
    model_number: Mapped[Optional[str]] = mapped_column(String(255))
    part_type: Mapped[Optional[str]] = mapped_column(String(100))
    technical_specs: Mapped[Optional[str]] = mapped_column(Text)
    country_of_origin: Mapped[Optional[str]] = mapped_column(String(100))
    oem_only: Mapped[Optional[bool]] = mapped_column(Boolean)
    substitute_available: Mapped[Optional[bool]] = mapped_column(Boolean)
    obsolescence_risk: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    attributes: Mapped[list[PartAttribute]] = relationship(
        "PartAttribute", back_populates="part", cascade="all, delete-orphan"
    )
    assessments: Mapped[list[Assessment]] = relationship(
        "Assessment", back_populates="part", cascade="all, delete-orphan"
    )
    research_sources: Mapped[list[ResearchSource]] = relationship(
        "ResearchSource", back_populates="part", cascade="all, delete-orphan"
    )


class PartAttribute(Base):
    """Single attribute value for a spare part – with confidence and source tracking."""

    __tablename__ = "part_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("spare_parts.id"), nullable=False)
    attribute_name: Mapped[str] = mapped_column(String(255), nullable=False)
    attribute_value: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(255))
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    confidence_level: Mapped[float] = mapped_column(Float, default=0.5)
    # 1=ERP/Manual  2=OEM  3=Distributor  4=Web  5=AI
    source_tier: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    part: Mapped[SparePart] = relationship("SparePart", back_populates="attributes")

    __table_args__ = (UniqueConstraint("part_id", "attribute_name"),)


class ResearchSource(Base):
    """Web / reference source URL for a spare part."""

    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("spare_parts.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    snippet: Mapped[Optional[str]] = mapped_column(Text)
    source_type: Mapped[Optional[str]] = mapped_column(String(100))
    reliability_tier: Mapped[int] = mapped_column(Integer, default=4)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    part: Mapped[SparePart] = relationship("SparePart", back_populates="research_sources")


class Assessment(Base):
    """Full criticality assessment for a spare part."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("spare_parts.id"), nullable=False)

    # ── Legacy fields (questionnaire-based scoring) ────────────────────────────
    operations_score: Mapped[float] = mapped_column(Float, default=0.0)
    supply_chain_score: Mapped[float] = mapped_column(Float, default=0.0)
    inventory_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    override_label: Mapped[Optional[str]] = mapped_column(String(50))
    override_reason: Mapped[Optional[str]] = mapped_column(Text)
    key_reasons: Mapped[Optional[str]] = mapped_column(Text)
    override_rules_triggered: Mapped[Optional[str]] = mapped_column(Text)
    missing_attributes: Mapped[Optional[str]] = mapped_column(Text)
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_version: Mapped[int] = mapped_column(Integer, default=1)

    # ── NWC 4-dimension fields ─────────────────────────────────────────────────
    # Dimension options (A/B/C/D selected by LLM)
    nwc_operations_option: Mapped[Optional[str]] = mapped_column(String(5))
    nwc_operations_score: Mapped[Optional[int]] = mapped_column(Integer)
    nwc_water_quality_option: Mapped[Optional[str]] = mapped_column(String(5))
    nwc_water_quality_score: Mapped[Optional[int]] = mapped_column(Integer)
    nwc_availability_option: Mapped[Optional[str]] = mapped_column(String(5))
    nwc_availability_score: Mapped[Optional[int]] = mapped_column(Integer)
    nwc_safety_option: Mapped[Optional[str]] = mapped_column(String(5))
    nwc_safety_score: Mapped[Optional[int]] = mapped_column(Integer)
    nwc_total_score: Mapped[Optional[int]] = mapped_column(Integer)
    # Strategic | Very Critical | Semi-Critical | Non-Critical
    nwc_label: Mapped[Optional[str]] = mapped_column(String(50))
    nwc_strategic_rules: Mapped[Optional[str]] = mapped_column(Text)   # JSON array

    # ── LLM provenance ─────────────────────────────────────────────────────────
    analysis_json: Mapped[Optional[str]] = mapped_column(Text)         # full LLM JSON
    model_used: Mapped[Optional[str]] = mapped_column(String(150))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(50))
    inference_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # ── Overall confidence from LLM ────────────────────────────────────────────
    analysis_confidence: Mapped[Optional[float]] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    part: Mapped[SparePart] = relationship("SparePart", back_populates="assessments")
    answers: Mapped[list[QuestionnaireAnswer]] = relationship(
        "QuestionnaireAnswer",
        back_populates="assessment",
        cascade="all, delete-orphan",
    )
    dimension_scores: Mapped[list[NWCDimensionScore]] = relationship(
        "NWCDimensionScore",
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class NWCDimensionScore(Base):
    """
    Detailed per-dimension analysis record for NWC assessments.
    Stores the full LLM reasoning, confidence, and evidence for each dimension.
    """

    __tablename__ = "nwc_dimension_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    dimension: Mapped[str] = mapped_column(String(50), nullable=False)  # operations | water_quality | availability | safety
    selected_option: Mapped[str] = mapped_column(String(5), nullable=False)
    option_label: Mapped[Optional[str]] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    sources: Mapped[Optional[str]] = mapped_column(Text)               # JSON array
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    assessment: Mapped[Assessment] = relationship(
        "Assessment", back_populates="dimension_scores"
    )

    __table_args__ = (UniqueConstraint("assessment_id", "dimension"),)



class QuestionnaireAnswer(Base):
    """Answer to one questionnaire question within an assessment."""

    __tablename__ = "questionnaire_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id"), nullable=False
    )
    question_db_id: Mapped[int] = mapped_column(
        ForeignKey("questionnaire_questions.id"), nullable=False
    )
    answer_value: Mapped[Optional[str]] = mapped_column(Text)
    answer_score: Mapped[float] = mapped_column(Float, default=0.0)
    answered_by: Mapped[str] = mapped_column(
        String(50), default="user"
    )  # user | research | system
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    assessment: Mapped[Assessment] = relationship(
        "Assessment", back_populates="answers"
    )
    question: Mapped[QuestionnaireQuestion] = relationship(
        "QuestionnaireQuestion", back_populates="answers"
    )
