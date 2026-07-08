"""
Rule-based criticality scoring engine.

Every question maps to a set of answer options (label → value_key → risk score 0-100).
Scores are aggregated with per-question weights inside each scenario, then combined
with the scenario-level weights to produce a final 0-100 score.

Override rules take precedence over the numeric threshold.
"""

from __future__ import annotations

import logging
from typing import Any

from src.utils.helpers import AnswerOption, AssessmentResult, SubmittedAnswer

logger = logging.getLogger(__name__)

# ── Scenario keys (match DB column 'scenario') ─────────────────────────────────
SCENARIO_OPS = "Scenario 1 - Operations Criticality"
SCENARIO_SC = "Scenario 2 - Supply Chain Risk"
SCENARIO_INV = "Scenario 3 - Inventory & Financial"

# ── Scenario-level weights (must sum to 1.0) ───────────────────────────────────
SCENARIO_WEIGHTS: dict[str, float] = {
    SCENARIO_OPS: 0.45,
    SCENARIO_SC: 0.35,
    SCENARIO_INV: 0.20,
}

# ── Score thresholds ───────────────────────────────────────────────────────────
THRESHOLD_CRITICAL = 70.0
THRESHOLD_SEMI = 40.0

# ── Per-question rubric ────────────────────────────────────────────────────────
# Key: (scenario, question_id)
# Value: {"weight": float, "options": list[AnswerOption]}
SCORING_RUBRICS: dict[tuple[str, str], dict[str, Any]] = {

    # ── Scenario 1: Operations Criticality ────────────────────────────────────
    (SCENARIO_OPS, "Q1"): {
        "weight": 0.25,
        "options": [
            AnswerOption("Complete operational shutdown", "complete_shutdown", 100),
            AnswerOption("Partial shutdown", "partial_shutdown", 60),
            AnswerOption("Reduced capacity only", "reduced_capacity", 30),
            AnswerOption("No operational impact", "no_impact", 0),
        ],
    },
    (SCENARIO_OPS, "Q2"): {
        "weight": 0.15,
        "options": [
            AnswerOption("No backup or redundancy", "no_backup", 100),
            AnswerOption("Partial / limited backup", "partial_backup", 50),
            AnswerOption("Full backup available", "full_backup", 0),
        ],
    },
    (SCENARIO_OPS, "Q3"): {
        "weight": 0.10,
        "options": [
            AnswerOption("Within 1 hour (emergency)", "within_1hr", 100),
            AnswerOption("Within 4 hours", "within_4hr", 80),
            AnswerOption("Within 24 hours", "within_24hr", 60),
            AnswerOption("Within 1 week", "within_1wk", 30),
            AnswerOption("No urgency / flexible", "flexible", 0),
        ],
    },
    (SCENARIO_OPS, "Q4"): {
        "weight": 0.10,
        "options": [
            AnswerOption("Very high (>50% capacity loss or >$10k/hr)", "very_high", 100),
            AnswerOption("High (25-50% capacity or $1k-10k/hr)", "high", 75),
            AnswerOption("Medium (10-25% capacity or $100-1k/hr)", "medium", 50),
            AnswerOption("Low (<10% capacity or <$100/hr)", "low", 25),
            AnswerOption("Negligible / no loss", "negligible", 0),
        ],
    },
    (SCENARIO_OPS, "Q5"): {
        "weight": 0.20,
        "options": [
            AnswerOption("Yes — single point of failure", "yes_spof", 100),
            AnswerOption("No — redundancy exists", "no_spof", 0),
        ],
    },
    (SCENARIO_OPS, "Q6"): {
        "weight": 0.05,
        "options": [
            AnswerOption("Core production / critical service", "core_production", 100),
            AnswerOption("Important production process", "important_process", 60),
            AnswerOption("Support / utility function", "support_function", 30),
            AnswerOption("Administrative / non-core", "administrative", 0),
        ],
    },
    (SCENARIO_OPS, "Q7"): {
        "weight": 0.05,
        "options": [
            AnswerOption("No workaround possible", "no_workaround", 100),
            AnswerOption("Limited workaround (reduced efficiency)", "limited_workaround", 60),
            AnswerOption("Temporary workaround available", "temp_workaround", 30),
            AnswerOption("Easy workaround exists", "easy_workaround", 0),
        ],
    },
    (SCENARIO_OPS, "Q8"): {
        "weight": 0.05,
        "options": [
            AnswerOption("Weekly or more frequently", "weekly", 100),
            AnswerOption("Monthly", "monthly", 75),
            AnswerOption("Quarterly", "quarterly", 50),
            AnswerOption("Annually", "annually", 25),
            AnswerOption("Rarely / never failed", "rarely", 0),
        ],
    },
    (SCENARIO_OPS, "Q9"): {
        "weight": 0.03,
        "options": [
            AnswerOption("Yes — complex / lengthy calibration", "yes_complex", 100),
            AnswerOption("Yes — minor calibration needed", "yes_minor", 50),
            AnswerOption("No calibration required", "no_calibration", 0),
        ],
    },
    (SCENARIO_OPS, "Q10"): {
        "weight": 0.02,
        "options": [
            AnswerOption("Must be replaced — long procurement", "replace_long", 100),
            AnswerOption("Must be replaced — short procurement", "replace_short", 50),
            AnswerOption("Repairable on-site / locally", "repairable", 0),
        ],
    },

    # ── Scenario 2: Supply Chain Risk ─────────────────────────────────────────
    (SCENARIO_SC, "Q1"): {
        "weight": 0.25,
        "options": [
            AnswerOption("More than 6 months", "gt_6mo", 100),
            AnswerOption("1–6 months", "one_to_6mo", 75),
            AnswerOption("2–4 weeks", "two_to_4wk", 50),
            AnswerOption("1–2 weeks", "one_to_2wk", 25),
            AnswerOption("Less than 1 week", "lt_1wk", 0),
        ],
    },
    (SCENARIO_SC, "Q2"): {
        "weight": 0.10,
        "options": [
            AnswerOption("High variability (unpredictable)", "high_var", 100),
            AnswerOption("Moderate variability", "medium_var", 50),
            AnswerOption("Low / consistent lead time", "low_var", 0),
        ],
    },
    (SCENARIO_SC, "Q3"): {
        "weight": 0.20,
        "options": [
            AnswerOption("Single source only", "single_source", 100),
            AnswerOption("2 suppliers", "two_suppliers", 75),
            AnswerOption("3–5 suppliers", "three_to_five", 50),
            AnswerOption("More than 5 suppliers", "many_suppliers", 0),
        ],
    },
    (SCENARIO_SC, "Q4"): {
        "weight": 0.10,
        "options": [
            AnswerOption("Yes — OEM only", "yes_oem", 100),
            AnswerOption("No — alternatives exist", "no_oem", 0),
        ],
    },
    (SCENARIO_SC, "Q5"): {
        "weight": 0.15,
        "options": [
            AnswerOption("No approved substitutes", "no_substitute", 100),
            AnswerOption("Substitutes exist but not approved", "unapproved_sub", 50),
            AnswerOption("Approved substitutes available", "approved_sub", 0),
        ],
    },
    (SCENARIO_SC, "Q6"): {
        "weight": 0.05,
        "options": [
            AnswerOption("OTIF below 80% (unreliable)", "otif_lt80", 100),
            AnswerOption("OTIF 80–90%", "otif_80_90", 50),
            AnswerOption("OTIF above 90% (reliable)", "otif_gt90", 0),
        ],
    },
    (SCENARIO_SC, "Q7"): {
        "weight": 0.05,
        "options": [
            AnswerOption("No local supplier available", "no_local", 100),
            AnswerOption("Overseas supplier only", "overseas_only", 50),
            AnswerOption("Local supplier / distributor available", "local_available", 0),
        ],
    },
    (SCENARIO_SC, "Q8"): {
        "weight": 0.05,
        "options": [
            AnswerOption("Single country import (high concentration)", "single_country", 100),
            AnswerOption("Multi-country but complex import", "multi_complex", 50),
            AnswerOption("Locally manufactured / sourced", "local_mfg", 0),
        ],
    },
    (SCENARIO_SC, "Q9"): {
        "weight": 0.02,
        "options": [
            AnswerOption("High customs / regulatory complexity", "high_customs", 100),
            AnswerOption("Some complexity (permits, licences)", "some_customs", 50),
            AnswerOption("No customs complexity", "no_customs", 0),
        ],
    },
    (SCENARIO_SC, "Q10"): {
        "weight": 0.03,
        "options": [
            AnswerOption("High obsolescence risk (discontinued)", "high_obs", 100),
            AnswerOption("Medium risk (aging model)", "medium_obs", 50),
            AnswerOption("Low obsolescence risk (current model)", "low_obs", 0),
        ],
    },

    # ── Scenario 3: Inventory & Financial ─────────────────────────────────────
    (SCENARIO_INV, "Q1"): {
        "weight": 0.28,
        "options": [
            AnswerOption("Zero stock — none available", "zero_stock", 100),
            AnswerOption("Below minimum safety level", "below_min", 75),
            AnswerOption("At minimum safety level", "at_min", 50),
            AnswerOption("Above minimum, below target", "above_min", 25),
            AnswerOption("Healthy stock level (at/above target)", "healthy_stock", 0),
        ],
    },
    (SCENARIO_INV, "Q2"): {
        "weight": 0.10,
        "options": [
            AnswerOption("High (>10 units/month)", "high_consumption", 100),
            AnswerOption("Medium (3–10 units/month)", "medium_consumption", 75),
            AnswerOption("Low (1–2 units/month)", "low_consumption", 50),
            AnswerOption("Occasional (<1 unit/month)", "occasional", 25),
            AnswerOption("Rarely consumed", "rarely_consumed", 0),
        ],
    },
    (SCENARIO_INV, "Q3"): {
        "weight": 0.10,
        "options": [
            AnswerOption("More than 24 times last year", "gt24", 100),
            AnswerOption("12–24 times last year", "12_to_24", 75),
            AnswerOption("4–12 times last year", "4_to_12", 50),
            AnswerOption("1–3 times last year", "1_to_3", 25),
            AnswerOption("Never used in last year", "never_used", 0),
        ],
    },
    (SCENARIO_INV, "Q4"): {
        "weight": 0.23,
        "options": [
            AnswerOption("Yes — multiple stockouts recorded", "multiple_stockouts", 100),
            AnswerOption("Yes — one stockout recorded", "one_stockout", 50),
            AnswerOption("No stockouts on record", "no_stockouts", 0),
        ],
    },
    (SCENARIO_INV, "Q5"): {
        "weight": 0.10,
        "options": [
            AnswerOption("Very high (>$10,000/unit)", "very_high_cost", 100),
            AnswerOption("High ($1,000–$10,000/unit)", "high_cost", 75),
            AnswerOption("Medium ($100–$1,000/unit)", "medium_cost", 50),
            AnswerOption("Low ($10–$100/unit)", "low_cost", 25),
            AnswerOption("Very low (<$10/unit)", "very_low_cost", 0),
        ],
    },
    (SCENARIO_INV, "Q6"): {
        "weight": 0.05,
        "options": [
            AnswerOption("Very high (>$50,000/transaction)", "very_high_spend", 100),
            AnswerOption("High ($10,000–$50,000/transaction)", "high_spend", 75),
            AnswerOption("Medium ($1,000–$10,000/transaction)", "medium_spend", 50),
            AnswerOption("Low (<$1,000/transaction)", "low_spend", 0),
        ],
    },
    (SCENARIO_INV, "Q7"): {
        "weight": 0.05,
        "options": [
            AnswerOption("Large annual single purchase only", "large_annual", 100),
            AnswerOption("Medium quarterly orders", "medium_quarterly", 50),
            AnswerOption("Small frequent orders (agile)", "small_frequent", 0),
        ],
    },
    (SCENARIO_INV, "Q8"): {
        "weight": 0.04,
        "options": [
            AnswerOption("Frequent delays vs. promised dates", "frequent_delays", 100),
            AnswerOption("Occasional delays", "occasional_delays", 50),
            AnswerOption("Rarely or never delayed", "rarely_delayed", 0),
        ],
    },
    (SCENARIO_INV, "Q9"): {
        "weight": 0.03,
        "options": [
            AnswerOption("Consumption increasing significantly", "consumption_increasing", 100),
            AnswerOption("Consumption stable", "consumption_stable", 50),
            AnswerOption("Consumption decreasing", "consumption_decreasing", 0),
        ],
    },
    (SCENARIO_INV, "Q10"): {
        "weight": 0.03,
        "options": [
            AnswerOption("High value (>10% of inventory value)", "high_value_pct", 100),
            AnswerOption("Medium value (1-10% of inventory value)", "medium_value_pct", 50),
            AnswerOption("Low value (<1% of inventory value)", "low_value_pct", 0),
        ],
    },
}


# ── Override rules ─────────────────────────────────────────────────────────────
# Each rule is a dict with:
#   name, description, check(answers_by_key) → bool, result: str label

def _answers_val(
    answers: dict[tuple[str, str], SubmittedAnswer],
    scenario: str,
    qid: str,
) -> str | None:
    a = answers.get((scenario, qid))
    return a.answer_value if a else None


OVERRIDE_RULES: list[dict] = [
    {
        "name": "complete_shutdown_no_backup",
        "description": "Complete shutdown + no backup → Critical",
        "check": lambda a: (
            _answers_val(a, SCENARIO_OPS, "Q1") == "complete_shutdown"
            and _answers_val(a, SCENARIO_OPS, "Q2") == "no_backup"
        ),
        "result": "Critical",
    },
    {
        "name": "spof_long_lead_time",
        "description": "Single point of failure + long lead time (>4 wk) → Critical",
        "check": lambda a: (
            _answers_val(a, SCENARIO_OPS, "Q5") == "yes_spof"
            and _answers_val(a, SCENARIO_SC, "Q1") in ("gt_6mo", "one_to_6mo", "two_to_4wk")
        ),
        "result": "Critical",
    },
    {
        "name": "sole_source_no_sub_no_stock",
        "description": "Single supplier + no substitute + zero/low stock → Critical",
        "check": lambda a: (
            _answers_val(a, SCENARIO_SC, "Q3") == "single_source"
            and _answers_val(a, SCENARIO_SC, "Q5") == "no_substitute"
            and _answers_val(a, SCENARIO_INV, "Q1") in ("zero_stock", "below_min")
        ),
        "result": "Critical",
    },
    {
        "name": "partial_impact_high_supply_risk",
        "description": "Partial operational impact + high lead time or single source → Semi Critical",
        "check": lambda a: (
            _answers_val(a, SCENARIO_OPS, "Q1") == "partial_shutdown"
            and (
                _answers_val(a, SCENARIO_SC, "Q1") in ("gt_6mo", "one_to_6mo")
                or _answers_val(a, SCENARIO_SC, "Q3") == "single_source"
            )
        ),
        "result": "Semi Critical",
    },
    {
        "name": "no_impact_good_supply",
        "description": (
            "No operational impact + backup + multiple suppliers + short lead time"
            " + approved substitute + adequate stock → Not Critical"
        ),
        "check": lambda a: (
            _answers_val(a, SCENARIO_OPS, "Q1") == "no_impact"
            and _answers_val(a, SCENARIO_OPS, "Q2") in ("full_backup", "partial_backup")
            and _answers_val(a, SCENARIO_SC, "Q3") in ("three_to_five", "many_suppliers")
            and _answers_val(a, SCENARIO_SC, "Q1") in ("lt_1wk", "one_to_2wk")
            and _answers_val(a, SCENARIO_SC, "Q5") == "approved_sub"
            and _answers_val(a, SCENARIO_INV, "Q1") in ("above_min", "healthy_stock")
        ),
        "result": "Not Critical",
    },
]


# ── Public API ─────────────────────────────────────────────────────────────────

def get_answer_options(scenario: str, question_id: str) -> list[AnswerOption]:
    """Return the list of selectable answer options for a given question."""
    rubric = SCORING_RUBRICS.get((scenario, question_id))
    if rubric is None:
        return []
    return rubric["options"]


def score_answer(scenario: str, question_id: str, answer_value: str) -> float:
    """Return the risk score (0-100) for a given answer value key."""
    rubric = SCORING_RUBRICS.get((scenario, question_id))
    if rubric is None:
        return 50.0  # unknown → moderate risk
    for opt in rubric["options"]:
        if opt.value == answer_value:
            return opt.score
    return 50.0


def calculate_assessment(
    submitted_answers: list[SubmittedAnswer],
) -> AssessmentResult:
    """
    Compute criticality scores and label from a list of submitted answers.

    Unknown / unanswered questions default to 50 (moderate risk) and are
    flagged in missing_attributes.
    """
    # Index answers by (scenario, question_id) for O(1) lookup
    answers_by_key: dict[tuple[str, str], SubmittedAnswer] = {
        (a.scenario, a.question_id): a for a in submitted_answers
    }

    per_q_scores: dict[str, float] = {}
    scenario_scores: dict[str, float] = {}
    missing: list[str] = []
    low_conf: list[str] = []

    for scenario in (SCENARIO_OPS, SCENARIO_SC, SCENARIO_INV):
        questions = [k for k in SCORING_RUBRICS if k[0] == scenario]
        total_weight = sum(SCORING_RUBRICS[k]["weight"] for k in questions)
        weighted_sum = 0.0

        for (s, qid) in questions:
            rubric = SCORING_RUBRICS[(s, qid)]
            w = rubric["weight"]
            ans = answers_by_key.get((s, qid))

            if ans is None or ans.answer_value is None:
                score = 50.0  # unanswered → moderate
                missing.append(f"{s} / {qid}")
            else:
                score = ans.answer_score
                if ans.confidence < 0.6:
                    low_conf.append(f"{s} / {qid} (conf={ans.confidence:.0%})")

            per_q_scores[f"{s}|{qid}"] = score
            weighted_sum += score * w

        # Normalise in case question weights don't sum exactly to 1
        scenario_scores[scenario] = (weighted_sum / total_weight) if total_weight else 50.0

    ops_score = round(scenario_scores[SCENARIO_OPS], 1)
    sc_score = round(scenario_scores[SCENARIO_SC], 1)
    inv_score = round(scenario_scores[SCENARIO_INV], 1)
    total = round(
        ops_score * SCENARIO_WEIGHTS[SCENARIO_OPS]
        + sc_score * SCENARIO_WEIGHTS[SCENARIO_SC]
        + inv_score * SCENARIO_WEIGHTS[SCENARIO_INV],
        1,
    )

    # Base label from thresholds
    if total >= THRESHOLD_CRITICAL:
        label = "Critical"
    elif total >= THRESHOLD_SEMI:
        label = "Semi Critical"
    else:
        label = "Not Critical"

    # Apply override rules (last matching rule wins, ordered from most to least critical)
    triggered_rules: list[str] = []
    for rule in OVERRIDE_RULES:
        try:
            if rule["check"](answers_by_key):
                label = rule["result"]
                triggered_rules.append(rule["name"])
                logger.info("Override rule triggered: %s → %s", rule["name"], label)
        except Exception as exc:
            logger.warning("Override rule %s error: %s", rule["name"], exc)

    key_reasons = _build_key_reasons(
        answers_by_key, ops_score, sc_score, inv_score, triggered_rules
    )

    return AssessmentResult(
        operations_score=ops_score,
        supply_chain_score=sc_score,
        inventory_score=inv_score,
        total_score=total,
        label=label,
        key_reasons=key_reasons,
        override_rules_triggered=triggered_rules,
        missing_attributes=missing,
        low_confidence_attributes=low_conf,
        per_question_scores=per_q_scores,
    )


def _build_key_reasons(
    answers: dict[tuple[str, str], SubmittedAnswer],
    ops: float,
    sc: float,
    inv: float,
    triggered: list[str],
) -> list[str]:
    reasons: list[str] = []

    def val(scenario: str, qid: str) -> str | None:
        a = answers.get((scenario, qid))
        return a.answer_value if a else None

    # Operations
    if val(SCENARIO_OPS, "Q1") == "complete_shutdown":
        reasons.append("Part failure causes complete operational shutdown")
    elif val(SCENARIO_OPS, "Q1") == "partial_shutdown":
        reasons.append("Part failure causes partial operational shutdown")
    if val(SCENARIO_OPS, "Q5") == "yes_spof":
        reasons.append("Identified as a single point of failure")
    if val(SCENARIO_OPS, "Q2") == "no_backup":
        reasons.append("No backup or redundancy exists")

    # Supply Chain
    if val(SCENARIO_SC, "Q3") == "single_source":
        reasons.append("Only one supplier available (sole source)")
    if val(SCENARIO_SC, "Q1") in ("gt_6mo", "one_to_6mo"):
        reasons.append("Long procurement lead time (≥1 month)")
    if val(SCENARIO_SC, "Q5") == "no_substitute":
        reasons.append("No approved substitute parts available")
    if val(SCENARIO_SC, "Q4") == "yes_oem":
        reasons.append("OEM-only part — limited sourcing flexibility")
    if val(SCENARIO_SC, "Q10") == "high_obs":
        reasons.append("High obsolescence risk")

    # Inventory
    if val(SCENARIO_INV, "Q1") == "zero_stock":
        reasons.append("Zero current stock on hand")
    elif val(SCENARIO_INV, "Q1") == "below_min":
        reasons.append("Stock below minimum safety level")
    if val(SCENARIO_INV, "Q4") == "multiple_stockouts":
        reasons.append("Multiple historical stockouts recorded")

    # Override rules triggered
    for rule_name in triggered:
        for rule in OVERRIDE_RULES:
            if rule["name"] == rule_name:
                reasons.append(f"Override rule: {rule['description']}")

    # Score-based fallback
    if not reasons:
        if ops >= 70:
            reasons.append(f"High operational criticality score ({ops:.0f}/100)")
        if sc >= 70:
            reasons.append(f"High supply chain risk score ({sc:.0f}/100)")
        if inv >= 70:
            reasons.append(f"High inventory risk score ({inv:.0f}/100)")

    return reasons[:8]  # cap for readability
