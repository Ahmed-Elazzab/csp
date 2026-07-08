"""
Question relevance engine.

Ranks the pool of unanswered questions by how relevant they are to the
current part, then returns the top-N most important ones.

Relevance score = base_relevance (within_weight × scenario_weight)
                + Σ context_bonuses

Context bonuses are applied when known part attributes suggest a specific
question is more informative for this particular part.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.questionnaire.prefill_engine import PrefilledAnswer
from src.questionnaire.question_bank import QUESTION_BANK, QuestionDefinition
from src.utils.helpers import ResearchResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUESTIONS = 15

# ─────────────────────────────────────────────────────────────────────────────
# Part context builder
# ─────────────────────────────────────────────────────────────────────────────

# Part types associated with high operational criticality
_INDUSTRIAL_PART_TYPES = frozenset(
    "pump motor valve compressor turbine gearbox actuator fan blower conveyor"
    " generator boiler heat_exchanger reactor agitator mixer".split()
)

# Part types that typically require calibration
_INSTRUMENT_PART_TYPES = frozenset(
    "sensor transmitter analyzer transducer controller plc hmi drive inverter"
    " flow_meter pressure_gauge level_sensor temperature_sensor".split()
)

_LOCAL_COUNTRY_HINTS = frozenset(
    "local domestic national saudi ksa uae gcc".split()
)


def build_part_context(
    research_result: Optional[ResearchResult],
    db_attributes: dict,
    prefills: list[PrefilledAnswer],
) -> dict:
    """
    Derive a flat context dict from all available part data.
    Used by the relevance engine to compute context bonuses.
    """
    ctx: dict = {}

    # ── From research_result ──────────────────────────────────────────────────
    if research_result:
        pt = (research_result.part_type or "").lower()
        ctx["part_type"] = pt
        ctx["is_industrial"] = any(kw in pt for kw in _INDUSTRIAL_PART_TYPES)
        ctx["is_instrument"] = any(kw in pt for kw in _INSTRUMENT_PART_TYPES)

        coo = (research_result.country_of_origin or "").lower()
        ctx["country_of_origin"] = coo
        ctx["is_foreign"] = bool(coo) and not any(h in coo for h in _LOCAL_COUNTRY_HINTS)

        ctx["oem_only"] = research_result.oem_only          # True / False / None
        ctx["substitute_available"] = research_result.substitute_available
        ctx["obsolescence_risk"] = (research_result.obsolescence_risk or "").lower()
        ctx["research_confidence"] = research_result.overall_confidence or 0.5
        ctx["has_manufacturer"] = bool(research_result.manufacturer)
    else:
        ctx.update(
            part_type="", is_industrial=False, is_instrument=False,
            is_foreign=False, country_of_origin="", oem_only=None,
            substitute_available=None, obsolescence_risk="",
            research_confidence=0.0, has_manufacturer=False,
        )

    # ── From DB attributes ────────────────────────────────────────────────────
    def _db_val(key: str) -> Optional[str]:
        entry = db_attributes.get(key)
        return entry["value"] if entry else None

    ctx["has_stock_data"] = _db_val("stock_on_hand_quantity") is not None
    ctx["has_cost_data"] = _db_val("unit_purchase_cost") is not None
    ctx["has_consumption_data"] = _db_val("monthly_consumption_rate") is not None

    stock_raw = _db_val("stock_on_hand_quantity")
    if stock_raw is not None:
        try:
            ctx["stock_level"] = float(stock_raw.replace(",", "").strip())
        except (ValueError, AttributeError):
            ctx["stock_level"] = None
    else:
        ctx["stock_level"] = None

    # ── From prefills ─────────────────────────────────────────────────────────
    pf_map = {p.question_id: p for p in prefills}
    ctx["prefill_ops_q1"] = pf_map.get("ops_q1")   # shutdown answer
    ctx["prefill_sc_q1"] = pf_map.get("sc_q1")     # lead time answer
    ctx["prefill_sc_q3"] = pf_map.get("sc_q3")     # supplier count answer

    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Per-question context bonus calculator
# ─────────────────────────────────────────────────────────────────────────────

def _context_bonus(q: QuestionDefinition, ctx: dict) -> float:
    bonus = 0.0
    qid = q.id

    # ── Operations bonuses ─────────────────────────────────────────────────
    if q.scenario_key == "operations":
        if ctx.get("is_industrial"):
            # Industrial parts → operations questions carry more weight
            if qid in ("ops_q1", "ops_q5", "ops_q2"):
                bonus += 0.020
        if ctx.get("is_instrument"):
            # Instruments/sensors → calibration question is very relevant
            if qid == "ops_q9":
                bonus += 0.030
        # If we know shutdown IS critical → TTR, production loss, workaround all matter
        pf_q1 = ctx.get("prefill_ops_q1")
        if pf_q1 and pf_q1.answer_value in ("complete_shutdown", "partial_shutdown"):
            if qid in ("ops_q3", "ops_q4", "ops_q7"):
                bonus += 0.025

    # ── Supply chain bonuses ───────────────────────────────────────────────
    elif q.scenario_key == "supply_chain":
        if ctx.get("oem_only") is True:
            # OEM-only → lead time, supplier count, local availability more critical
            if qid in ("sc_q1", "sc_q3", "sc_q7"):
                bonus += 0.020
        if ctx.get("is_foreign"):
            # Foreign origin → import, customs questions more relevant
            if qid in ("sc_q8", "sc_q9"):
                bonus += 0.025
        obs = ctx.get("obsolescence_risk", "")
        if obs in ("medium", "high"):
            if qid == "sc_q10":
                bonus += 0.030
        # Single/few suppliers → reliability, local availability matter more
        pf_q3 = ctx.get("prefill_sc_q3")
        if pf_q3 and pf_q3.answer_value in ("single_source", "two_suppliers"):
            if qid in ("sc_q6", "sc_q7"):
                bonus += 0.015
        # Long lead time known → local availability even more critical
        pf_lt = ctx.get("prefill_sc_q1")
        if pf_lt and pf_lt.answer_value in ("gt_6mo", "one_to_6mo"):
            if qid in ("sc_q7", "sc_q2"):
                bonus += 0.015

    # ── Inventory bonuses ──────────────────────────────────────────────────
    elif q.scenario_key == "inventory":
        if not ctx.get("has_stock_data"):
            # No stock data → all inventory questions are more relevant
            bonus += 0.010
        if not ctx.get("has_cost_data") and qid == "inv_q5":
            bonus += 0.020
        if not ctx.get("has_consumption_data") and qid in ("inv_q2", "inv_q3"):
            bonus += 0.015
        stock = ctx.get("stock_level")
        if stock is not None and stock == 0 and qid == "inv_q4":
            # Zero stock → past stockouts question very relevant
            bonus += 0.020

    # ── Low research confidence → prioritise high-weight questions ──────────
    if ctx.get("research_confidence", 1.0) < 0.5:
        if q.within_scenario_weight >= 0.15:
            bonus += 0.010

    return bonus


# ─────────────────────────────────────────────────────────────────────────────
# Public ranking function
# ─────────────────────────────────────────────────────────────────────────────

def rank_questions_for_part(
    prefilled_ids: set[str],
    part_context: dict,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
) -> list[QuestionDefinition]:
    """
    Return the top-N unanswered questions ranked by relevance to the current part.

    Parameters
    ----------
    prefilled_ids  : set of canonical question ids that have been auto-answered
    part_context   : dict built by build_part_context()
    max_questions  : cap on visible questions (default 15)

    Returns
    -------
    Ordered list of QuestionDefinition (most relevant first), length ≤ max_questions.
    """
    unanswered = [q for q in QUESTION_BANK if q.id not in prefilled_ids]

    scored: list[tuple[float, QuestionDefinition]] = []
    for q in unanswered:
        relevance = q.base_relevance + _context_bonus(q, part_context)
        scored.append((relevance, q))

    # Sort descending by relevance, then by scenario order (stable)
    scored.sort(key=lambda x: -x[0])

    top = [q for _, q in scored[:max_questions]]

    logger.info(
        "Relevance engine: %d unanswered, showing %d (max=%d)",
        len(unanswered),
        len(top),
        max_questions,
    )
    return top
