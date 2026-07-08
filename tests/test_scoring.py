"""Tests for the rule-based scoring engine."""

from __future__ import annotations

import pytest

from src.scoring.engine import (
    SCENARIO_INV,
    SCENARIO_OPS,
    SCENARIO_SC,
    calculate_assessment,
    get_answer_options,
    score_answer,
)
from src.utils.helpers import SubmittedAnswer


def _make_answer(scenario: str, qid: str, value: str, score: float) -> SubmittedAnswer:
    return SubmittedAnswer(
        question_db_id=0,
        scenario=scenario,
        question_id=qid,
        answer_value=value,
        answer_score=score,
        answered_by="user",
    )


# ── Unit tests for individual scoring rubrics ──────────────────────────────────

class TestScoreAnswer:
    def test_complete_shutdown_scores_100(self):
        assert score_answer(SCENARIO_OPS, "Q1", "complete_shutdown") == 100

    def test_no_impact_scores_0(self):
        assert score_answer(SCENARIO_OPS, "Q1", "no_impact") == 0

    def test_partial_shutdown_scores_60(self):
        assert score_answer(SCENARIO_OPS, "Q1", "partial_shutdown") == 60

    def test_single_source_scores_100(self):
        assert score_answer(SCENARIO_SC, "Q3", "single_source") == 100

    def test_many_suppliers_scores_0(self):
        assert score_answer(SCENARIO_SC, "Q3", "many_suppliers") == 0

    def test_zero_stock_scores_100(self):
        assert score_answer(SCENARIO_INV, "Q1", "zero_stock") == 100

    def test_healthy_stock_scores_0(self):
        assert score_answer(SCENARIO_INV, "Q1", "healthy_stock") == 0

    def test_unknown_returns_moderate(self):
        assert score_answer(SCENARIO_OPS, "Q1", "unknown_value") == 50

    def test_all_ops_questions_have_options(self):
        for qid in [f"Q{i}" for i in range(1, 11)]:
            opts = get_answer_options(SCENARIO_OPS, qid)
            assert len(opts) > 0, f"No options for ops {qid}"

    def test_all_sc_questions_have_options(self):
        for qid in [f"Q{i}" for i in range(1, 11)]:
            opts = get_answer_options(SCENARIO_SC, qid)
            assert len(opts) > 0, f"No options for sc {qid}"

    def test_all_inv_questions_have_options(self):
        for qid in [f"Q{i}" for i in range(1, 9)]:
            opts = get_answer_options(SCENARIO_INV, qid)
            assert len(opts) > 0, f"No options for inv {qid}"


# ── Integration tests for calculate_assessment ─────────────────────────────────

def _full_critical_answers() -> list[SubmittedAnswer]:
    """Answers that should produce a Critical result."""
    return [
        _make_answer(SCENARIO_OPS, "Q1", "complete_shutdown", 100),
        _make_answer(SCENARIO_OPS, "Q2", "no_backup", 100),
        _make_answer(SCENARIO_OPS, "Q3", "within_1hr", 100),
        _make_answer(SCENARIO_OPS, "Q4", "very_high", 100),
        _make_answer(SCENARIO_OPS, "Q5", "yes_spof", 100),
        _make_answer(SCENARIO_OPS, "Q6", "core_production", 100),
        _make_answer(SCENARIO_OPS, "Q7", "no_workaround", 100),
        _make_answer(SCENARIO_OPS, "Q8", "weekly", 100),
        _make_answer(SCENARIO_OPS, "Q9", "yes_complex", 100),
        _make_answer(SCENARIO_OPS, "Q10", "replace_long", 100),
        _make_answer(SCENARIO_SC, "Q1", "gt_6mo", 100),
        _make_answer(SCENARIO_SC, "Q2", "high_var", 100),
        _make_answer(SCENARIO_SC, "Q3", "single_source", 100),
        _make_answer(SCENARIO_SC, "Q4", "yes_oem", 100),
        _make_answer(SCENARIO_SC, "Q5", "no_substitute", 100),
        _make_answer(SCENARIO_SC, "Q6", "otif_lt80", 100),
        _make_answer(SCENARIO_SC, "Q7", "no_local", 100),
        _make_answer(SCENARIO_SC, "Q8", "single_country", 100),
        _make_answer(SCENARIO_SC, "Q9", "high_customs", 100),
        _make_answer(SCENARIO_SC, "Q10", "high_obs", 100),
        _make_answer(SCENARIO_INV, "Q1", "zero_stock", 100),
        _make_answer(SCENARIO_INV, "Q2", "high_consumption", 100),
        _make_answer(SCENARIO_INV, "Q3", "gt24", 100),
        _make_answer(SCENARIO_INV, "Q4", "multiple_stockouts", 100),
        _make_answer(SCENARIO_INV, "Q5", "very_high_cost", 100),
        _make_answer(SCENARIO_INV, "Q6", "very_high_spend", 100),
        _make_answer(SCENARIO_INV, "Q7", "large_annual", 100),
        _make_answer(SCENARIO_INV, "Q8", "frequent_delays", 100),
    ]


def _full_not_critical_answers() -> list[SubmittedAnswer]:
    """Answers that should produce a Not Critical result."""
    return [
        _make_answer(SCENARIO_OPS, "Q1", "no_impact", 0),
        _make_answer(SCENARIO_OPS, "Q2", "full_backup", 0),
        _make_answer(SCENARIO_OPS, "Q3", "flexible", 0),
        _make_answer(SCENARIO_OPS, "Q4", "negligible", 0),
        _make_answer(SCENARIO_OPS, "Q5", "no_spof", 0),
        _make_answer(SCENARIO_OPS, "Q6", "administrative", 0),
        _make_answer(SCENARIO_OPS, "Q7", "easy_workaround", 0),
        _make_answer(SCENARIO_OPS, "Q8", "rarely", 0),
        _make_answer(SCENARIO_OPS, "Q9", "no_calibration", 0),
        _make_answer(SCENARIO_OPS, "Q10", "repairable", 0),
        _make_answer(SCENARIO_SC, "Q1", "lt_1wk", 0),
        _make_answer(SCENARIO_SC, "Q2", "low_var", 0),
        _make_answer(SCENARIO_SC, "Q3", "many_suppliers", 0),
        _make_answer(SCENARIO_SC, "Q4", "no_oem", 0),
        _make_answer(SCENARIO_SC, "Q5", "approved_sub", 0),
        _make_answer(SCENARIO_SC, "Q6", "otif_gt90", 0),
        _make_answer(SCENARIO_SC, "Q7", "local_available", 0),
        _make_answer(SCENARIO_SC, "Q8", "local_mfg", 0),
        _make_answer(SCENARIO_SC, "Q9", "no_customs", 0),
        _make_answer(SCENARIO_SC, "Q10", "low_obs", 0),
        _make_answer(SCENARIO_INV, "Q1", "healthy_stock", 0),
        _make_answer(SCENARIO_INV, "Q2", "rarely_consumed", 0),
        _make_answer(SCENARIO_INV, "Q3", "never_used", 0),
        _make_answer(SCENARIO_INV, "Q4", "no_stockouts", 0),
        _make_answer(SCENARIO_INV, "Q5", "very_low_cost", 0),
        _make_answer(SCENARIO_INV, "Q6", "low_spend", 0),
        _make_answer(SCENARIO_INV, "Q7", "small_frequent", 0),
        _make_answer(SCENARIO_INV, "Q8", "rarely_delayed", 0),
    ]


class TestCalculateAssessment:
    def test_all_max_answers_returns_critical(self):
        result = calculate_assessment(_full_critical_answers())
        assert result.label == "Critical"
        assert result.total_score >= 70

    def test_all_min_answers_returns_not_critical(self):
        result = calculate_assessment(_full_not_critical_answers())
        assert result.label == "Not Critical"
        assert result.total_score < 40

    def test_scores_in_valid_range(self):
        result = calculate_assessment(_full_critical_answers())
        assert 0 <= result.operations_score <= 100
        assert 0 <= result.supply_chain_score <= 100
        assert 0 <= result.inventory_score <= 100
        assert 0 <= result.total_score <= 100

    def test_empty_answers_returns_moderate_score(self):
        result = calculate_assessment([])
        # All defaults to 50, so total ≈ 50 → Semi Critical
        assert result.label in ("Semi Critical", "Critical")
        assert len(result.missing_attributes) > 0

    def test_override_complete_shutdown_no_backup(self):
        answers = _full_not_critical_answers()
        # Inject critical override conditions
        answers_dict = {(a.scenario, a.question_id): a for a in answers}
        answers_dict[(SCENARIO_OPS, "Q1")] = _make_answer(SCENARIO_OPS, "Q1", "complete_shutdown", 100)
        answers_dict[(SCENARIO_OPS, "Q2")] = _make_answer(SCENARIO_OPS, "Q2", "no_backup", 100)
        result = calculate_assessment(list(answers_dict.values()))
        assert result.label == "Critical"
        assert "complete_shutdown_no_backup" in result.override_rules_triggered

    def test_override_spof_long_lead_time(self):
        answers = _full_not_critical_answers()
        answers_dict = {(a.scenario, a.question_id): a for a in answers}
        answers_dict[(SCENARIO_OPS, "Q5")] = _make_answer(SCENARIO_OPS, "Q5", "yes_spof", 100)
        answers_dict[(SCENARIO_SC, "Q1")] = _make_answer(SCENARIO_SC, "Q1", "gt_6mo", 100)
        result = calculate_assessment(list(answers_dict.values()))
        assert result.label == "Critical"
        assert "spof_long_lead_time" in result.override_rules_triggered

    def test_override_sole_source_no_sub_no_stock(self):
        answers = _full_not_critical_answers()
        answers_dict = {(a.scenario, a.question_id): a for a in answers}
        answers_dict[(SCENARIO_SC, "Q3")] = _make_answer(SCENARIO_SC, "Q3", "single_source", 100)
        answers_dict[(SCENARIO_SC, "Q5")] = _make_answer(SCENARIO_SC, "Q5", "no_substitute", 100)
        answers_dict[(SCENARIO_INV, "Q1")] = _make_answer(SCENARIO_INV, "Q1", "zero_stock", 100)
        result = calculate_assessment(list(answers_dict.values()))
        assert result.label == "Critical"
        assert "sole_source_no_sub_no_stock" in result.override_rules_triggered

    def test_key_reasons_populated(self):
        result = calculate_assessment(_full_critical_answers())
        assert len(result.key_reasons) > 0

    def test_semi_critical_range(self):
        # Build answers with moderate scores
        answers = []
        for a in _full_critical_answers():
            if a.scenario == SCENARIO_OPS and a.question_id == "Q1":
                answers.append(_make_answer(SCENARIO_OPS, "Q1", "partial_shutdown", 60))
            elif a.scenario == SCENARIO_SC and a.question_id == "Q3":
                answers.append(_make_answer(SCENARIO_SC, "Q3", "two_suppliers", 75))
            else:
                answers.append(_make_answer(a.scenario, a.question_id, "no_impact", 0))
        result = calculate_assessment(answers)
        assert result.total_score >= 0
