"""
Prefill engine: maps part data from earlier workflow steps to question answers.

Sources checked, in descending trust order:
  1. DB part_attributes (tier 1 = user / ERP manual input)   confidence = 1.0
  2. Session research_result.attributes (tier 4/5 web / AI)  confidence from AttributeData
  3. Session research_result direct fields (oem_only, etc.)  confidence = research overall

A PrefilledAnswer is produced for any question whose data_mapping_keys contain
a known attribute with a mappable value.  Questions without a prefill remain
in the "needs user input" pool and are candidates for the top-15 visible list.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from src.questionnaire.question_bank import QUESTION_BANK, QuestionDefinition
from src.scoring.engine import score_answer
from src.utils.helpers import ResearchResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data-transfer object
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PrefilledAnswer:
    """One auto-answered question from earlier workflow data."""

    question_id: str       # canonical bank id "ops_q1"
    scenario: str          # full DB scenario string
    db_question_id: str    # "Q1"
    answer_value: str      # scoring engine value key
    answer_score: float    # 0-100
    source: str            # "user_input" | "research" | "part_data"
    confidence: float      # 0.0 – 1.0
    source_detail: str     # human-readable description

    def to_submitted_answer(self, db_id: int):
        """Convert to SubmittedAnswer for the scoring engine."""
        from src.utils.helpers import SubmittedAnswer

        return SubmittedAnswer(
            question_db_id=db_id,
            scenario=self.scenario,
            question_id=self.db_question_id,
            answer_value=self.answer_value,
            answer_score=self.answer_score,
            answered_by=self.source,
            confidence=self.confidence,
            source=self.source_detail,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Low-level value converters
# ─────────────────────────────────────────────────────────────────────────────

def _bool_val(raw: str) -> Optional[bool]:
    v = raw.strip().lower()
    if v in ("true", "yes", "1", "y"):
        return True
    if v in ("false", "no", "0", "n"):
        return False
    return None


def _extract_number(raw: str) -> Optional[float]:
    cleaned = re.sub(r"[,$€£¥%]", "", raw).strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Per-attribute converters  (raw string → scoring engine value key or None)
# ─────────────────────────────────────────────────────────────────────────────

def _convert_oem_only(raw: str) -> Optional[str]:
    b = _bool_val(raw)
    if b is True:
        return "yes_oem"
    if b is False:
        return "no_oem"
    return None


def _convert_substitute(raw: str) -> Optional[str]:
    b = _bool_val(raw)
    if b is True:
        return "approved_sub"
    if b is False:
        return "no_substitute"
    return None


def _convert_backup(raw: str) -> Optional[str]:
    b = _bool_val(raw)
    if b is True:
        return "full_backup"
    if b is False:
        return "no_backup"
    v = raw.strip().lower()
    if "partial" in v:
        return "partial_backup"
    return None


def _convert_spof(raw: str) -> Optional[str]:
    b = _bool_val(raw)
    if b is True:
        return "yes_spof"
    if b is False:
        return "no_spof"
    return None


def _convert_repairable(raw: str) -> Optional[str]:
    b = _bool_val(raw)
    if b is True:
        return "repairable"
    if b is False:
        return "replace_short"
    return None


def _convert_calibration(raw: str) -> Optional[str]:
    b = _bool_val(raw)
    if b is True:
        return "yes_minor"
    if b is False:
        return "no_calibration"
    v = raw.strip().lower()
    if "complex" in v or "lengthy" in v:
        return "yes_complex"
    return None


def _convert_local_availability(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    if v in ("true", "yes", "local", "1"):
        return "local_available"
    if v in ("false", "no", "0"):
        return "no_local"
    if "overseas" in v:
        return "overseas_only"
    return None


def _convert_obsolescence(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    MAP = {"high": "high_obs", "medium": "medium_obs", "low": "low_obs",
           "discontinued": "high_obs", "end of life": "high_obs", "eol": "high_obs"}
    return MAP.get(v)


def _convert_lead_time_variability(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    MAP = {"high": "high_var", "medium": "medium_var", "low": "low_var",
           "variable": "high_var", "consistent": "low_var"}
    return MAP.get(v)


def _convert_lead_time(raw: str) -> Optional[str]:
    """Map free-text lead time to scoring key."""
    v = raw.strip().lower()
    # Pattern: look for numeric + time unit
    if re.search(r"\b(>6|more than 6)\s*month", v):
        return "gt_6mo"
    if re.search(r"\b[1-6]\s*month|\b(one|two|three|four|five|six)\s*month", v):
        return "one_to_6mo"
    if re.search(r"\b[2-4]\s*week|\b(two|three|four)\s*week", v):
        return "two_to_4wk"
    if re.search(r"\b[1-2]\s*week|\b(one|two)\s*week", v):
        return "one_to_2wk"
    if re.search(r"\b[1-7]\s*day|\blt\b.*week|\bless.*week", v):
        return "lt_1wk"
    # Sample values: "1 hour; 1 day; 2 weeks; 1 month; 6 months"
    if "hour" in v or "day" in v:
        return "lt_1wk"
    if "month" in v:
        return "one_to_6mo"
    return None


def _convert_supplier_count(raw: str) -> Optional[str]:
    n = _extract_number(raw)
    if n is None:
        return None
    if n <= 1:
        return "single_source"
    if n <= 2:
        return "two_suppliers"
    if n <= 5:
        return "three_to_five"
    return "many_suppliers"


def _convert_stock_level(raw: str) -> Optional[str]:
    n = _extract_number(raw)
    if n is None:
        return None
    if n == 0:
        return "zero_stock"
    if n <= 1:
        return "below_min"
    if n <= 5:
        return "at_min"
    if n <= 20:
        return "above_min"
    return "healthy_stock"


def _convert_monthly_consumption(raw: str) -> Optional[str]:
    n = _extract_number(raw)
    if n is None:
        return None
    if n == 0:
        return "rarely_consumed"
    if n < 1:
        return "occasional"
    if n <= 2:
        return "low_consumption"
    if n <= 10:
        return "medium_consumption"
    return "high_consumption"


def _convert_annual_consumption(raw: str) -> Optional[str]:
    n = _extract_number(raw)
    if n is None:
        return None
    if n == 0:
        return "never_used"
    if n <= 3:
        return "1_to_3"
    if n <= 12:
        return "4_to_12"
    if n <= 24:
        return "12_to_24"
    return "gt24"


def _convert_stockout_history(raw: str) -> Optional[str]:
    n = _extract_number(raw)
    if n is None:
        return None
    if n == 0:
        return "no_stockouts"
    if n == 1:
        return "one_stockout"
    return "multiple_stockouts"


def _convert_unit_cost(raw: str) -> Optional[str]:
    n = _extract_number(raw)
    if n is None:
        return None
    if n < 10:
        return "very_low_cost"
    if n < 100:
        return "low_cost"
    if n < 1_000:
        return "medium_cost"
    if n < 10_000:
        return "high_cost"
    return "very_high_cost"


def _convert_shutdown_impact(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    if "complete" in v or "full" in v:
        return "complete_shutdown"
    if "partial" in v:
        return "partial_shutdown"
    if "reduced" in v or "capacity" in v:
        return "reduced_capacity"
    if "no impact" in v or "none" in v:
        return "no_impact"
    return None


def _convert_process_impact(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    if v in ("high",):
        return "core_production"
    if v in ("medium",):
        return "important_process"
    if v in ("low",):
        return "support_function"
    return None


def _convert_breakdown_usage(raw: str) -> Optional[str]:
    """Map unplanned breakdown usage level to failure frequency."""
    v = raw.strip().lower()
    if v == "high":
        return "weekly"
    if v == "medium":
        return "monthly"
    if v == "low":
        return "quarterly"
    return None


def _convert_country_origin(raw: str) -> Optional[str]:
    """Infer import dependency from country string."""
    v = raw.strip().lower()
    if not v or v in ("unknown", "n/a", "-"):
        return None
    # Very rough heuristic — local production indicators
    local_hints = ("local", "domestic", "national")
    if any(h in v for h in local_hints):
        return "local_mfg"
    return "single_country"


def _convert_customs_complexity(raw: str) -> Optional[str]:
    v = raw.strip().lower()
    MAP = {"high": "high_customs", "medium": "some_customs", "low": "no_customs"}
    return MAP.get(v)


def _convert_consumption_trend(raw: str) -> Optional[str]:
    """36-month consumption: higher than 12-month → increasing."""
    n36 = _extract_number(raw)
    if n36 is None:
        return None
    # Rough signal only – exact comparison needs 12m data too
    if n36 > 30:
        return "consumption_increasing"
    if n36 == 0:
        return "consumption_decreasing"
    return "consumption_stable"


def _convert_supplier_reliability(raw: str) -> Optional[str]:
    """Map OTIF % string to reliability answer."""
    v = raw.strip().rstrip("%")
    n = _extract_number(v)
    if n is None:
        return None
    if n < 80:
        return "otif_lt80"
    if n < 90:
        return "otif_80_90"
    return "otif_gt90"


# ── Master converter dispatch ──────────────────────────────────────────────────
# Maps attribute key → converter function
_CONVERTERS: dict[str, callable] = {
    "oem_only_requirement": _convert_oem_only,
    "oem_only": _convert_oem_only,
    "approved_substitute_availability": _convert_substitute,
    "substitute_available": _convert_substitute,
    "redundancy_backup_equipment_available": _convert_backup,
    "single_point_of_failure_flag": _convert_spof,
    "repairability_flag": _convert_repairable,
    "calibration_commissioning_requirement": _convert_calibration,
    "local_presence_distributor_availability": _convert_local_availability,
    "obsolescence_risk": _convert_obsolescence,
    "lead_time_variability": _convert_lead_time_variability,
    "procurement_lead_time": _convert_lead_time,
    "supplier_count": _convert_supplier_count,
    "stock_on_hand_quantity": _convert_stock_level,
    "monthly_consumption_rate": _convert_monthly_consumption,
    "consumption_in_last_12_months": _convert_annual_consumption,
    "stockout_history": _convert_stockout_history,
    "unit_purchase_cost": _convert_unit_cost,
    "operational_shutdown_impact": _convert_shutdown_impact,
    "affected_production_line_process": _convert_process_impact,
    "unplanned_breakdown_usage": _convert_breakdown_usage,
    "country_of_origin_concentration": _convert_country_origin,
    "country_of_origin": _convert_country_origin,
    "import_customs_complexity": _convert_customs_complexity,
    "consumption_in_last_36_months": _convert_consumption_trend,
    "supplier_reliability_otif": _convert_supplier_reliability,
    "maximum_allowable_downtime_time_to_recover": _convert_lead_time,
    "production_service_loss_per_downtime_hour": lambda raw: None,  # too complex to map
    "mean_time_between_failures_mtbf": _convert_lead_time,  # reuse time converter
}


# ─────────────────────────────────────────────────────────────────────────────
# PrefillEngine
# ─────────────────────────────────────────────────────────────────────────────

class PrefillEngine:
    """
    Produces a list of PrefilledAnswer objects by scanning all available
    part data sources and matching them to question data_mapping_keys.
    """

    CONFIDENCE_BY_TIER = {1: 1.0, 2: 0.95, 3: 0.85, 4: 0.70, 5: 0.55}

    def compute_prefills(
        self,
        research_result: Optional[ResearchResult],
        db_attributes: dict,  # {attr_name: {value, confidence, source, source_url, source_tier}}
    ) -> list[PrefilledAnswer]:
        """
        Return all questions that can be auto-answered from available data.

        Parameters
        ----------
        research_result : ResearchResult or None
        db_attributes   : dict from DatabaseAgent.get_part_attributes()
        """
        # Build a merged attribute pool, keyed by attribute name.
        # Higher-trust sources override lower-trust ones.
        pool: dict[str, dict] = {}  # attr_name → {value, confidence, source, tier}

        # 1. Start with research_result.attributes (tier 4/5)
        if research_result:
            for attr_name, attr_data in research_result.attributes.items():
                pool[attr_name] = {
                    "value": attr_data.value,
                    "confidence": attr_data.confidence,
                    "source": attr_data.source or "Research",
                    "tier": attr_data.source_tier,
                    "source_type": "research",
                }

            # 2. Inject direct fields from ResearchResult (tier 4, overall confidence)
            conf = research_result.overall_confidence or 0.5
            direct_fields = {
                "oem_only": research_result.oem_only,
                "substitute_available": research_result.substitute_available,
                "obsolescence_risk": research_result.obsolescence_risk,
                "country_of_origin": research_result.country_of_origin,
            }
            for field_name, value in direct_fields.items():
                if value is not None:
                    raw = str(value).lower() if isinstance(value, bool) else str(value)
                    if field_name not in pool or pool[field_name]["tier"] > 4:
                        pool[field_name] = {
                            "value": raw,
                            "confidence": conf,
                            "source": "Research (direct field)",
                            "tier": 4,
                            "source_type": "research",
                        }

        # 3. DB attributes override (usually higher trust, tier 1 for manual edits)
        for attr_name, attr_dict in db_attributes.items():
            existing = pool.get(attr_name)
            tier = attr_dict.get("source_tier", 4)
            existing_tier = existing["tier"] if existing else 99
            if tier <= existing_tier:
                pool[attr_name] = {
                    "value": str(attr_dict.get("value", "")),
                    "confidence": attr_dict.get("confidence", 0.7),
                    "source": attr_dict.get("source", "Database"),
                    "tier": tier,
                    "source_type": "user_input" if tier == 1 else "part_data",
                }

        # 4. Walk every question and attempt prefill
        prefills: list[PrefilledAnswer] = []
        for q in QUESTION_BANK:
            pf = self._try_prefill_question(q, pool)
            if pf is not None:
                prefills.append(pf)

        logger.info(
            "Prefill engine: %d/%d questions auto-answered",
            len(prefills),
            len(QUESTION_BANK),
        )
        return prefills

    def _try_prefill_question(
        self,
        q: QuestionDefinition,
        pool: dict[str, dict],
    ) -> Optional[PrefilledAnswer]:
        """Try each data_mapping_key in order; return first successful conversion."""
        for attr_key in q.data_mapping_keys:
            entry = pool.get(attr_key)
            if entry is None:
                continue
            raw_value: str = entry["value"]
            if not raw_value:
                continue

            converter = _CONVERTERS.get(attr_key)
            if converter is None:
                continue

            try:
                answer_key = converter(raw_value)
            except Exception as exc:
                logger.debug("Converter error for %s/%s: %s", attr_key, raw_value, exc)
                continue

            if answer_key is None:
                continue

            # Validate answer_key exists in options
            valid_keys = {opt.value for opt in q.answer_options}
            if answer_key not in valid_keys:
                logger.debug(
                    "Converter produced unknown key '%s' for question %s", answer_key, q.id
                )
                continue

            score = score_answer(q.scenario, q.question_id, answer_key)
            source_type = entry.get("source_type", "research")
            tier = entry.get("tier", 4)
            conf = entry.get("confidence", self.CONFIDENCE_BY_TIER.get(tier, 0.6))

            return PrefilledAnswer(
                question_id=q.id,
                scenario=q.scenario,
                db_question_id=q.question_id,
                answer_value=answer_key,
                answer_score=score,
                source=source_type,
                confidence=conf,
                source_detail=entry.get("source", "Research"),
            )
        return None
