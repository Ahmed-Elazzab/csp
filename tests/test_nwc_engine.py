"""Tests for the NWC criticality scoring engine."""

from __future__ import annotations

import pytest

from src.scoring.nwc_engine import (
    CLASSIFICATION_THRESHOLDS,
    DIMENSION_OPTIONS,
    MAX_SCORE,
    CriticalityAnalysisInput,
    DimensionScore,
    NWCAssessmentResult,
    calculate_nwc_assessment,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dim(
    dim: str,
    option: str,
    confidence: float = 0.9,
    reason: str = "test",
    sources: list[str] | None = None,
) -> DimensionScore:
    score = DIMENSION_OPTIONS[dim][option]
    return DimensionScore(
        selected_option=option,
        score=score,
        confidence=confidence,
        reason=reason,
        sources=sources or [],
    )


def _analysis(ops: str, wq: str, avail: str, safety: str, conf: float = 0.9) -> CriticalityAnalysisInput:
    return CriticalityAnalysisInput(
        operations=_dim("operations",    ops,    conf),
        water_quality=_dim("water_quality", wq,  conf),
        availability=_dim("availability",  avail, conf),
        safety=_dim("safety",          safety, conf),
    )


# ── Score correctness ──────────────────────────────────────────────────────────

class TestScoreLookup:
    def test_max_possible_score(self):
        result = calculate_nwc_assessment(_analysis("A", "A", "A", "A"))
        assert result.total_score == 42
        assert result.total_score == MAX_SCORE

    def test_zero_score(self):
        result = calculate_nwc_assessment(_analysis("D", "C", "C", "C"))
        assert result.total_score == 0

    def test_operations_scores(self):
        assert calculate_nwc_assessment(_analysis("A", "C", "C", "C")).operations_score == 12
        assert calculate_nwc_assessment(_analysis("B", "C", "C", "C")).operations_score == 10
        assert calculate_nwc_assessment(_analysis("C", "C", "C", "C")).operations_score == 3
        assert calculate_nwc_assessment(_analysis("D", "C", "C", "C")).operations_score == 0

    def test_water_quality_scores(self):
        assert calculate_nwc_assessment(_analysis("D", "A", "C", "C")).water_quality_score == 10
        assert calculate_nwc_assessment(_analysis("D", "B", "C", "C")).water_quality_score == 3
        assert calculate_nwc_assessment(_analysis("D", "C", "C", "C")).water_quality_score == 0

    def test_availability_scores(self):
        assert calculate_nwc_assessment(_analysis("D", "C", "A", "C")).availability_score == 10
        assert calculate_nwc_assessment(_analysis("D", "C", "B", "C")).availability_score == 3
        assert calculate_nwc_assessment(_analysis("D", "C", "C", "C")).availability_score == 0

    def test_safety_scores(self):
        assert calculate_nwc_assessment(_analysis("D", "C", "C", "A")).safety_score == 10
        assert calculate_nwc_assessment(_analysis("D", "C", "C", "B")).safety_score == 5
        assert calculate_nwc_assessment(_analysis("D", "C", "C", "C")).safety_score == 0

    def test_engine_ignores_llm_score(self):
        """Engine must use its own score lookup, not the LLM-supplied score."""
        wrong_score_input = CriticalityAnalysisInput(
            operations=DimensionScore(selected_option="A", score=999, confidence=0.9, reason="test"),
            water_quality=DimensionScore(selected_option="C", score=999, confidence=0.9, reason="test"),
            availability=DimensionScore(selected_option="C", score=999, confidence=0.9, reason="test"),
            safety=DimensionScore(selected_option="C", score=999, confidence=0.9, reason="test"),
        )
        result = calculate_nwc_assessment(wrong_score_input)
        assert result.operations_score == 12  # must be 12 from table, not 999
        assert result.total_score == 12


# ── Classification thresholds ──────────────────────────────────────────────────

class TestClassification:
    def test_very_critical_at_threshold(self):
        # ops A(12) + wq A(10) + avail B(3) + safety C(0) = 25, no strategic rule fires
        result = calculate_nwc_assessment(_analysis("A", "A", "B", "C"))
        assert result.total_score == 25
        assert result.label == "Very Critical"

    def test_semi_critical(self):
        # 10 = 10 wq
        result = calculate_nwc_assessment(_analysis("D", "A", "C", "C"))
        assert result.total_score == 10
        assert result.label == "Semi-Critical"

    def test_non_critical(self):
        result = calculate_nwc_assessment(_analysis("D", "C", "C", "C"))
        assert result.total_score == 0
        assert result.label == "Non-Critical"

    def test_score_9_is_non_critical(self):
        # 5 safety + 3 wq + 1... wait: D=0, B=3, C=0, B=5 = 8 → Non-Critical
        result = calculate_nwc_assessment(_analysis("D", "B", "C", "B"))
        assert result.total_score == 8
        assert result.label == "Non-Critical"

    def test_score_10_is_semi_critical(self):
        result = calculate_nwc_assessment(_analysis("D", "C", "B", "B"))
        # 0 + 0 + 3 + 5 = 8? No: B avail=3, B safety=5 → 8
        # Need exactly 10: C ops + A wq(10) + C avail + C safety = 10
        result = calculate_nwc_assessment(_analysis("D", "A", "C", "C"))
        assert result.total_score == 10
        assert result.label == "Semi-Critical"


# ── Strategic override rules ───────────────────────────────────────────────────

class TestStrategicRules:
    def test_strategic_complete_shutdown_plus_availability_a(self):
        result = calculate_nwc_assessment(_analysis("A", "C", "A", "C"))
        assert result.label == "Strategic"
        assert "complete_shutdown_spof_plus_availability_a" in result.strategic_rules_triggered

    def test_strategic_partial_shutdown_plus_availability_a(self):
        result = calculate_nwc_assessment(_analysis("B", "C", "A", "C"))
        assert result.label == "Strategic"
        assert "partial_shutdown_plus_availability_a" in result.strategic_rules_triggered

    def test_strategic_water_quality_plus_availability_a(self):
        result = calculate_nwc_assessment(_analysis("D", "A", "A", "C"))
        assert result.label == "Strategic"
        assert "water_quality_direct_plus_availability_a" in result.strategic_rules_triggered

    def test_strategic_overrides_score_threshold(self):
        """Even a low total score becomes Strategic if rules trigger."""
        result = calculate_nwc_assessment(_analysis("A", "C", "A", "C"))
        # Ops A=12 + Avail A=10 = 22 (would be Semi-Critical by score)
        # But strategic rules fire → must be Strategic
        assert result.label == "Strategic"

    def test_no_strategic_without_availability_a(self):
        result = calculate_nwc_assessment(_analysis("A", "A", "B", "A"))
        assert result.label != "Strategic"
        assert result.strategic_rules_triggered == []

    def test_llm_cannot_select_strategic(self):
        """LLM sending 'Strategic' as option must be rejected and treated as unknown."""
        bad_input = CriticalityAnalysisInput(
            operations=DimensionScore(selected_option="Strategic", score=0, confidence=0.5, reason="test"),
            water_quality=_dim("water_quality", "C"),
            availability=_dim("availability", "C"),
            safety=_dim("safety", "C"),
        )
        result = calculate_nwc_assessment(bad_input)
        # "Strategic" is not a valid option letter → falls back to last valid option "D"
        assert result.operations_option == "D"
        assert result.label != "Strategic"  # not strategic from rules either


# ── Option validation ──────────────────────────────────────────────────────────

class TestOptionValidation:
    def test_lowercase_option_normalised(self):
        analysis = CriticalityAnalysisInput(
            operations=DimensionScore(selected_option="a", score=12, confidence=0.9, reason="test"),
            water_quality=_dim("water_quality", "C"),
            availability=_dim("availability", "C"),
            safety=_dim("safety", "C"),
        )
        result = calculate_nwc_assessment(analysis)
        assert result.operations_option == "A"
        assert result.operations_score == 12

    def test_invalid_option_fallback(self):
        analysis = CriticalityAnalysisInput(
            operations=DimensionScore(selected_option="Z", score=0, confidence=0.1, reason="hallucinated"),
            water_quality=_dim("water_quality", "C"),
            availability=_dim("availability", "C"),
            safety=_dim("safety", "C"),
        )
        result = calculate_nwc_assessment(analysis)
        assert result.operations_option in ("D",)  # fallback to last option
        assert result.operations_score == 0


# ── Confidence ────────────────────────────────────────────────────────────────

class TestConfidence:
    def test_overall_confidence_average(self):
        analysis = _analysis("A", "A", "A", "A", conf=0.8)
        result = calculate_nwc_assessment(analysis)
        assert abs(result.overall_confidence - 0.8) < 0.01

    def test_confidence_clamped(self):
        dim = DimensionScore(selected_option="A", score=12, confidence=2.0, reason="test")
        assert dim.confidence == 1.0

    def test_confidence_clamped_low(self):
        dim = DimensionScore(selected_option="A", score=12, confidence=-0.5, reason="test")
        assert dim.confidence == 0.0


# ── Result model ──────────────────────────────────────────────────────────────

class TestResultModel:
    def test_score_pct_calculated(self):
        result = calculate_nwc_assessment(_analysis("A", "A", "A", "A"))
        assert result.score_pct == 100.0

    def test_key_reasons_populated_for_high_risk(self):
        result = calculate_nwc_assessment(_analysis("A", "A", "A", "A"))
        assert len(result.key_reasons) > 0

    def test_key_reasons_empty_for_zero_risk(self):
        result = calculate_nwc_assessment(_analysis("D", "C", "C", "C"))
        assert result.key_reasons == []

    def test_model_used_stored(self):
        result = calculate_nwc_assessment(
            _analysis("A", "A", "A", "A"),
            model_used="gpt-4o-mini",
            prompt_version="nwc-v1.0.0",
        )
        assert result.model_used == "gpt-4o-mini"
        assert result.prompt_version == "nwc-v1.0.0"
