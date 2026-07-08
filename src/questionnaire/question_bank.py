"""
Master bank of all 30 spare-part criticality questions with full metadata.

This is a **static Python config** – never loaded from DB at runtime.
The DB (seeded from Excel) overrides `question_text` when rendering, but
all scoring weights, relevance tags, and prefill mapping keys live here.

Question IDs follow the pattern:
  ops_q1 … ops_q10   → Scenario 1 – Operations Criticality
  sc_q1  … sc_q10   → Scenario 2 – Supply Chain Risk
  inv_q1 … inv_q10  → Scenario 3 – Inventory & Financial
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.scoring.engine import (
    SCENARIO_INV,
    SCENARIO_OPS,
    SCENARIO_SC,
    SCORING_RUBRICS,
    get_answer_options,
)
from src.utils.helpers import AnswerOption

# Scenario-level weights (must mirror scoring engine)
_SW = {"operations": 0.45, "supply_chain": 0.35, "inventory": 0.20}


@dataclass(frozen=True)
class QuestionDefinition:
    """Complete metadata for one questionnaire question."""

    id: str                               # canonical id e.g. "ops_q1"
    scenario: str                         # full DB scenario string
    scenario_key: str                     # "operations" | "supply_chain" | "inventory"
    question_id: str                      # "Q1" … "Q10" (matches DB)
    question_text: str                    # fallback text (DB text overrides at render time)
    within_scenario_weight: float         # copied from SCORING_RUBRICS
    relevance_tags: tuple[str, ...]       # for relevance ranking
    data_mapping_keys: tuple[str, ...]    # attribute keys that can prefill this question

    @property
    def answer_options(self) -> list[AnswerOption]:
        return get_answer_options(self.scenario, self.question_id)

    @property
    def base_relevance(self) -> float:
        """within_scenario_weight × scenario_weight → natural priority."""
        return self.within_scenario_weight * _SW.get(self.scenario_key, 0.25)


def _w(scenario: str, qid: str) -> float:
    """Pull within-scenario weight from the scoring engine (single source of truth)."""
    return SCORING_RUBRICS.get((scenario, qid), {}).get("weight", 0.03)


# ── 30-question bank ──────────────────────────────────────────────────────────

QUESTION_BANK: list[QuestionDefinition] = [

    # ── Scenario 1: Operations Criticality ───────────────────────────────────
    QuestionDefinition(
        id="ops_q1",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q1",
        question_text="Does failure of this spare part cause complete operational shutdown?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q1"),
        relevance_tags=("shutdown", "operational_impact", "production", "critical"),
        data_mapping_keys=("operational_shutdown_impact",),
    ),
    QuestionDefinition(
        id="ops_q2",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q2",
        question_text="Is there any backup or redundancy available for this part?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q2"),
        relevance_tags=("redundancy", "backup", "operational_resilience"),
        data_mapping_keys=("redundancy_backup_equipment_available",),
    ),
    QuestionDefinition(
        id="ops_q3",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q3",
        question_text="How quickly must the system be restored after failure?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q3"),
        relevance_tags=("recovery_time", "urgency", "ttr", "downtime"),
        data_mapping_keys=("maximum_allowable_downtime_time_to_recover",),
    ),
    QuestionDefinition(
        id="ops_q4",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q4",
        question_text="What is the estimated production/service loss per hour if unavailable?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q4"),
        relevance_tags=("production_loss", "financial_impact", "downtime_cost"),
        data_mapping_keys=("production_service_loss_per_downtime_hour",),
    ),
    QuestionDefinition(
        id="ops_q5",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q5",
        question_text="Is this part a single point of failure?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q5"),
        relevance_tags=("spof", "single_point_of_failure", "critical_path"),
        data_mapping_keys=("single_point_of_failure_flag",),
    ),
    QuestionDefinition(
        id="ops_q6",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q6",
        question_text="Which process or production line is affected?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q6"),
        relevance_tags=("process", "production_line", "asset"),
        data_mapping_keys=("affected_production_line_process",),
    ),
    QuestionDefinition(
        id="ops_q7",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q7",
        question_text="Can operations continue with workaround solutions?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q7"),
        relevance_tags=("workaround", "operational_continuity", "flexibility"),
        data_mapping_keys=(),
    ),
    QuestionDefinition(
        id="ops_q8",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q8",
        question_text="How often does this part fail historically?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q8"),
        relevance_tags=("failure_frequency", "mtbf", "reliability"),
        data_mapping_keys=("unplanned_breakdown_usage", "mean_time_between_failures_mtbf"),
    ),
    QuestionDefinition(
        id="ops_q9",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q9",
        question_text="Does replacement require specialized calibration or commissioning?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q9"),
        relevance_tags=("calibration", "commissioning", "instrument", "sensor"),
        data_mapping_keys=("calibration_commissioning_requirement",),
    ),
    QuestionDefinition(
        id="ops_q10",
        scenario=SCENARIO_OPS,
        scenario_key="operations",
        question_id="Q10",
        question_text="Is the part repairable or must it be replaced?",
        within_scenario_weight=_w(SCENARIO_OPS, "Q10"),
        relevance_tags=("repairability", "replace", "repair"),
        data_mapping_keys=("repairability_flag",),
    ),

    # ── Scenario 2: Supply Chain Risk ─────────────────────────────────────────
    QuestionDefinition(
        id="sc_q1",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q1",
        question_text="What is the typical procurement lead time for this spare part?",
        within_scenario_weight=_w(SCENARIO_SC, "Q1"),
        relevance_tags=("lead_time", "procurement", "supply_risk"),
        data_mapping_keys=("procurement_lead_time",),
    ),
    QuestionDefinition(
        id="sc_q2",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q2",
        question_text="How variable is the lead time across orders?",
        within_scenario_weight=_w(SCENARIO_SC, "Q2"),
        relevance_tags=("lead_time_variability", "planning_risk"),
        data_mapping_keys=("lead_time_variability",),
    ),
    QuestionDefinition(
        id="sc_q3",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q3",
        question_text="How many suppliers can provide this part?",
        within_scenario_weight=_w(SCENARIO_SC, "Q3"),
        relevance_tags=("supplier_count", "sole_source", "supply_diversity"),
        data_mapping_keys=("supplier_count",),
    ),
    QuestionDefinition(
        id="sc_q4",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q4",
        question_text="Is the part restricted to OEM only?",
        within_scenario_weight=_w(SCENARIO_SC, "Q4"),
        relevance_tags=("oem", "oem_only", "proprietary"),
        data_mapping_keys=("oem_only_requirement", "oem_only"),
    ),
    QuestionDefinition(
        id="sc_q5",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q5",
        question_text="Are there approved substitute parts available?",
        within_scenario_weight=_w(SCENARIO_SC, "Q5"),
        relevance_tags=("substitute", "alternative", "interchangeable"),
        data_mapping_keys=("approved_substitute_availability", "substitute_available"),
    ),
    QuestionDefinition(
        id="sc_q6",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q6",
        question_text="How reliable is the supplier in delivering on time?",
        within_scenario_weight=_w(SCENARIO_SC, "Q6"),
        relevance_tags=("supplier_reliability", "otif", "on_time"),
        data_mapping_keys=("supplier_reliability_otif",),
    ),
    QuestionDefinition(
        id="sc_q7",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q7",
        question_text="Is the supplier locally available?",
        within_scenario_weight=_w(SCENARIO_SC, "Q7"),
        relevance_tags=("local_supplier", "distributor", "emergency_procurement"),
        data_mapping_keys=("local_presence_distributor_availability",),
    ),
    QuestionDefinition(
        id="sc_q8",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q8",
        question_text="Is the part imported or dependent on a specific country?",
        within_scenario_weight=_w(SCENARIO_SC, "Q8"),
        relevance_tags=("import", "country_risk", "geopolitical"),
        data_mapping_keys=("country_of_origin_concentration", "country_of_origin"),
    ),
    QuestionDefinition(
        id="sc_q9",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q9",
        question_text="Are there customs or regulatory complexities for this item?",
        within_scenario_weight=_w(SCENARIO_SC, "Q9"),
        relevance_tags=("customs", "regulatory", "import_complexity"),
        data_mapping_keys=("import_customs_complexity",),
    ),
    QuestionDefinition(
        id="sc_q10",
        scenario=SCENARIO_SC,
        scenario_key="supply_chain",
        question_id="Q10",
        question_text="Is there risk of the part becoming obsolete?",
        within_scenario_weight=_w(SCENARIO_SC, "Q10"),
        relevance_tags=("obsolescence", "discontinued", "end_of_life"),
        data_mapping_keys=("obsolescence_risk",),
    ),

    # ── Scenario 3: Inventory & Financial ─────────────────────────────────────
    QuestionDefinition(
        id="inv_q1",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q1",
        question_text="What is the current stock level of this spare part?",
        within_scenario_weight=_w(SCENARIO_INV, "Q1"),
        relevance_tags=("stock_level", "inventory", "shortage_risk"),
        data_mapping_keys=("stock_on_hand_quantity",),
    ),
    QuestionDefinition(
        id="inv_q2",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q2",
        question_text="How frequently is this part consumed monthly?",
        within_scenario_weight=_w(SCENARIO_INV, "Q2"),
        relevance_tags=("consumption", "demand", "usage_rate"),
        data_mapping_keys=("monthly_consumption_rate",),
    ),
    QuestionDefinition(
        id="inv_q3",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q3",
        question_text="How many times was this part used in the last year?",
        within_scenario_weight=_w(SCENARIO_INV, "Q3"),
        relevance_tags=("annual_usage", "consumption_history"),
        data_mapping_keys=("consumption_in_last_12_months",),
    ),
    QuestionDefinition(
        id="inv_q4",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q4",
        question_text="Has this part experienced stockouts before?",
        within_scenario_weight=_w(SCENARIO_INV, "Q4"),
        relevance_tags=("stockout", "shortage_history", "availability_risk"),
        data_mapping_keys=("stockout_history",),
    ),
    QuestionDefinition(
        id="inv_q5",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q5",
        question_text="What is the unit cost of the part?",
        within_scenario_weight=_w(SCENARIO_INV, "Q5"),
        relevance_tags=("cost", "unit_price", "financial"),
        data_mapping_keys=("unit_purchase_cost",),
    ),
    QuestionDefinition(
        id="inv_q6",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q6",
        question_text="What is the average spend per transaction?",
        within_scenario_weight=_w(SCENARIO_INV, "Q6"),
        relevance_tags=("spend", "transaction_value", "financial"),
        data_mapping_keys=(),
    ),
    QuestionDefinition(
        id="inv_q7",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q7",
        question_text="What quantity is typically ordered?",
        within_scenario_weight=_w(SCENARIO_INV, "Q7"),
        relevance_tags=("order_quantity", "replenishment"),
        data_mapping_keys=(),
    ),
    QuestionDefinition(
        id="inv_q8",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q8",
        question_text="Are there delays in delivery compared to promised dates?",
        within_scenario_weight=_w(SCENARIO_INV, "Q8"),
        relevance_tags=("delivery_delay", "supplier_performance"),
        data_mapping_keys=(),
    ),
    QuestionDefinition(
        id="inv_q9",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q9",
        question_text="What is the trend of consumption over the last 3 years?",
        within_scenario_weight=_w(SCENARIO_INV, "Q9"),
        relevance_tags=("consumption_trend", "demand_forecast"),
        data_mapping_keys=("consumption_in_last_36_months",),
    ),
    QuestionDefinition(
        id="inv_q10",
        scenario=SCENARIO_INV,
        scenario_key="inventory",
        question_id="Q10",
        question_text="What percentage of inventory value does this part represent?",
        within_scenario_weight=_w(SCENARIO_INV, "Q10"),
        relevance_tags=("inventory_value", "abc_classification"),
        data_mapping_keys=(),
    ),
]

# ── Fast lookups ──────────────────────────────────────────────────────────────

QUESTIONS_BY_ID: dict[str, QuestionDefinition] = {q.id: q for q in QUESTION_BANK}

QUESTIONS_BY_DB_KEY: dict[tuple[str, str], QuestionDefinition] = {
    (q.scenario, q.question_id): q for q in QUESTION_BANK
}

TOTAL_QUESTIONS: int = len(QUESTION_BANK)  # 30
