"""
NWC Spare Parts Criticality Scoring Engine
==========================================

Deterministic, rule-based engine implementing the National Water Company (NWC)
spare-parts criticality methodology.

IMPORTANT ARCHITECTURE RULE
----------------------------
The LLM (Criticality Analysis Agent) determines the dimension options (A/B/C/D).
This engine is the SOLE authority for:
  - score look-up
  - total calculation
  - strategic override rules
  - final classification label

The LLM NEVER decides the final classification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


# ── Dimension option definitions ──────────────────────────────────────────────

DIMENSION_OPTIONS: dict[str, dict[str, int]] = {
    "operations": {
        "A": 12,   # Complete shutdown / Single Point of Failure
        "B": 10,   # Partial shutdown
        "C": 3,    # Operations affected but workaround exists
        "D": 0,    # No operational impact
    },
    "water_quality": {
        "A": 10,   # Direct degradation of water/sewage service
        "B": 3,    # Slight degradation
        "C": 0,    # No impact
    },
    "availability": {
        "A": 10,   # Backup required + no substitute + lead time > TTR + single source
        "B": 3,    # Substitute available
        "C": 0,    # Backup not required
    },
    "safety": {
        "A": 10,   # Risk to personnel, environment or infrastructure
        "B": 5,    # Partial risk
        "C": 0,    # No safety risk
    },
}

DIMENSION_LABELS: dict[str, dict[str, str]] = {
    "operations": {
        "A": "Complete shutdown – Single Point of Failure",
        "B": "Partial shutdown",
        "C": "Operations affected but workaround exists",
        "D": "No operational impact",
    },
    "water_quality": {
        "A": "Direct degradation of water/sewage service",
        "B": "Slight degradation",
        "C": "No impact on water quality",
    },
    "availability": {
        "A": "Backup required, no substitute, lead time > TTR, single source",
        "B": "Substitute available",
        "C": "Backup not required",
    },
    "safety": {
        "A": "Risk to personnel, environment or infrastructure",
        "B": "Partial risk",
        "C": "No safety risk",
    },
}

MAX_SCORE: int = sum(max(v.values()) for v in DIMENSION_OPTIONS.values())  # 42

# ── Classification thresholds (non-strategic labels, ascending order of risk) ──
# Easily updated for NWC policy changes without touching the engine logic.
CLASSIFICATION_THRESHOLDS: list[tuple[str, int]] = [
    ("Very Critical", 25),   # total >= 25
    ("Semi-Critical", 10),   # total >= 10
    ("Non-Critical", 0),     # total < 10
]

# ── Strategic override rules ───────────────────────────────────────────────────
# "Strategic" is NEVER assigned by the LLM.
# These deterministic conditions elevate a part to "Strategic" regardless of score.

@dataclass(frozen=True)
class StrategicRule:
    name: str
    description: str


STRATEGIC_RULES: list[StrategicRule] = [
    StrategicRule(
        "complete_shutdown_spof_plus_availability_a",
        "Complete shutdown / SPOF (Operations A) AND highest availability risk (Availability A)",
    ),
    StrategicRule(
        "partial_shutdown_plus_availability_a",
        "Partial shutdown (Operations B) AND highest availability risk (Availability A)",
    ),
    StrategicRule(
        "water_quality_direct_plus_availability_a",
        "Direct water quality degradation (Water Quality A) AND highest availability risk (Availability A)",
    ),
]


# ── Pydantic models for LLM → engine communication ────────────────────────────

class DimensionScore(BaseModel):
    """LLM output for a single criticality dimension."""

    selected_option: str
    score: int                # the LLM-proposed score – engine will OVERRIDE this
    confidence: float
    reason: str
    sources: list[str] = field(default_factory=list)

    @field_validator("selected_option")
    @classmethod
    def upper_option(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class CriticalityAnalysisInput(BaseModel):
    """Full LLM analysis output consumed by the scoring engine."""

    operations: DimensionScore
    water_quality: DimensionScore
    availability: DimensionScore
    safety: DimensionScore


class NWCAssessmentResult(BaseModel):
    """Final deterministic assessment result."""

    # Dimension options and engine-authoritative scores
    operations_option: str
    operations_score: int
    operations_label: str
    operations_reason: str
    operations_confidence: float
    operations_sources: list[str] = []

    water_quality_option: str
    water_quality_score: int
    water_quality_label: str
    water_quality_reason: str
    water_quality_confidence: float
    water_quality_sources: list[str] = []

    availability_option: str
    availability_score: int
    availability_label: str
    availability_reason: str
    availability_confidence: float
    availability_sources: list[str] = []

    safety_option: str
    safety_score: int
    safety_label: str
    safety_reason: str
    safety_confidence: float
    safety_sources: list[str] = []

    # Totals
    total_score: int
    max_score: int = MAX_SCORE
    score_pct: float

    # Classification
    label: Literal["Strategic", "Very Critical", "Semi-Critical", "Non-Critical"]
    strategic_rules_triggered: list[str] = []
    key_reasons: list[str] = []
    overall_confidence: float

    # Provenance
    model_used: str = ""
    prompt_version: str = ""


# ── Engine functions ───────────────────────────────────────────────────────────

def _resolve_option(dimension: str, option: str) -> str:
    """Normalise the option letter; fall back to lowest-risk option on invalid input."""
    valid = DIMENSION_OPTIONS.get(dimension, {})
    opt = option.strip().upper()
    if opt not in valid:
        fallback = list(valid.keys())[-1]
        logger.warning(
            "Invalid option '%s' for dimension '%s' – using fallback '%s'",
            opt, dimension, fallback,
        )
        return fallback
    return opt


def _check_strategic_rules(
    ops: str, wq: str, avail: str, safety: str
) -> list[str]:
    """Return list of triggered strategic rule names."""
    triggered: list[str] = []
    if ops == "A" and avail == "A":
        triggered.append("complete_shutdown_spof_plus_availability_a")
    if ops == "B" and avail == "A":
        triggered.append("partial_shutdown_plus_availability_a")
    if wq == "A" and avail == "A":
        triggered.append("water_quality_direct_plus_availability_a")
    return list(dict.fromkeys(triggered))  # deduplicate, preserve order


def _classify(total: int, strategic_rules: list[str]) -> str:
    if strategic_rules:
        return "Strategic"
    for label, threshold in CLASSIFICATION_THRESHOLDS:
        if total >= threshold:
            return label
    return "Non-Critical"


def calculate_nwc_assessment(
    analysis: CriticalityAnalysisInput,
    model_used: str = "",
    prompt_version: str = "",
) -> NWCAssessmentResult:
    """
    Convert LLM dimension analysis into a deterministic NWC assessment.

    The engine owns score lookup and classification.
    LLM-supplied scores are ignored; only the option letter matters.
    """
    # Resolve and validate options
    ops_opt   = _resolve_option("operations",    analysis.operations.selected_option)
    wq_opt    = _resolve_option("water_quality", analysis.water_quality.selected_option)
    avail_opt = _resolve_option("availability",  analysis.availability.selected_option)
    safety_opt = _resolve_option("safety",       analysis.safety.selected_option)

    # Engine-authoritative score lookup
    ops_score   = DIMENSION_OPTIONS["operations"][ops_opt]
    wq_score    = DIMENSION_OPTIONS["water_quality"][wq_opt]
    avail_score = DIMENSION_OPTIONS["availability"][avail_opt]
    safety_score = DIMENSION_OPTIONS["safety"][safety_opt]
    total = ops_score + wq_score + avail_score + safety_score

    # Strategic override rules
    strategic = _check_strategic_rules(ops_opt, wq_opt, avail_opt, safety_opt)

    # Final classification (deterministic)
    label = _classify(total, strategic)

    # Build key reasons
    reasons: list[str] = []
    if ops_opt == "A":
        reasons.append(f"Complete shutdown / SPOF — highest operational risk ({ops_score} pts)")
    elif ops_opt == "B":
        reasons.append(f"Partial shutdown risk ({ops_score} pts)")
    if wq_opt == "A":
        reasons.append(f"Direct water quality degradation ({wq_score} pts)")
    if avail_opt == "A":
        reasons.append(f"Highest availability risk — no substitute, single source, long lead time ({avail_score} pts)")
    if safety_opt == "A":
        reasons.append(f"Safety risk to personnel / environment / infrastructure ({safety_score} pts)")
    elif safety_opt == "B":
        reasons.append(f"Partial safety risk ({safety_score} pts)")
    for rule_name in strategic:
        rule_desc = next((r.description for r in STRATEGIC_RULES if r.name == rule_name), rule_name)
        reasons.append(f"Strategic rule triggered: {rule_desc}")

    overall_conf = round(
        (
            analysis.operations.confidence
            + analysis.water_quality.confidence
            + analysis.availability.confidence
            + analysis.safety.confidence
        ) / 4,
        3,
    )

    logger.info(
        "NWC assessment complete: ops=%s(%d) wq=%s(%d) avail=%s(%d) safety=%s(%d) "
        "total=%d/%d label=%s strategic=%s",
        ops_opt, ops_score, wq_opt, wq_score, avail_opt, avail_score,
        safety_opt, safety_score, total, MAX_SCORE, label, strategic,
    )

    return NWCAssessmentResult(
        operations_option=ops_opt,
        operations_score=ops_score,
        operations_label=DIMENSION_LABELS["operations"][ops_opt],
        operations_reason=analysis.operations.reason,
        operations_confidence=analysis.operations.confidence,
        operations_sources=analysis.operations.sources,
        water_quality_option=wq_opt,
        water_quality_score=wq_score,
        water_quality_label=DIMENSION_LABELS["water_quality"][wq_opt],
        water_quality_reason=analysis.water_quality.reason,
        water_quality_confidence=analysis.water_quality.confidence,
        water_quality_sources=analysis.water_quality.sources,
        availability_option=avail_opt,
        availability_score=avail_score,
        availability_label=DIMENSION_LABELS["availability"][avail_opt],
        availability_reason=analysis.availability.reason,
        availability_confidence=analysis.availability.confidence,
        availability_sources=analysis.availability.sources,
        safety_option=safety_opt,
        safety_score=safety_score,
        safety_label=DIMENSION_LABELS["safety"][safety_opt],
        safety_reason=analysis.safety.reason,
        safety_confidence=analysis.safety.confidence,
        safety_sources=analysis.safety.sources,
        total_score=total,
        score_pct=round(total / MAX_SCORE * 100, 1),
        label=label,
        strategic_rules_triggered=strategic,
        key_reasons=reasons,
        overall_confidence=overall_conf,
        model_used=model_used,
        prompt_version=prompt_version,
    )
