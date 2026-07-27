"""
Criticality Analysis Agent
===========================

LLM-powered agent that analyses spare-part evidence and determines the
appropriate NWC criticality dimension option for each of the four dimensions.

ARCHITECTURE RULES
------------------
1. This agent ONLY assigns dimension options (A/B/C/D) and provides reasoning.
2. It NEVER decides the final criticality classification.
3. Final classification is determined exclusively by src/scoring/nwc_engine.py.
4. Every fact cited must come from the supplied evidence.
5. If evidence is insufficient, the agent must declare low confidence rather
   than hallucinate.

The prompt version is embedded in every assessment for full auditability.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from src.config import get_settings
from src.llm.provider import BaseLLMProvider, LLMMessage, LLMResponse, get_llm_provider
from src.scoring.nwc_engine import (
    CriticalityAnalysisInput,
    DimensionScore,
    NWCAssessmentResult,
    calculate_nwc_assessment,
)
from src.utils.helpers import ResearchResult

logger = logging.getLogger(__name__)

PROMPT_VERSION = "nwc-v1.1.0"

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a certified spare-parts criticality analyst for the National Water Company (NWC) in Saudi Arabia.

You assess industrial spare parts used in water treatment plants, pumping stations, desalination facilities, sewage treatment plants, and water distribution networks.

Your task: analyse ALL available evidence and determine the correct option for each of the four NWC criticality dimensions.

═══════════════════════════════════════════════════════════
ABSOLUTE RULES — YOU MUST FOLLOW WITHOUT EXCEPTION
═══════════════════════════════════════════════════════════
1. Base every decision on evidence provided. Never invent, assume, or extrapolate unsupported facts.
2. If evidence for a dimension is absent or ambiguous → select the LOWEST-RISK option and set confidence below 0.5.
3. Cite the specific evidence (document name, URL, attribute value) that supports each selection.
4. NEVER select "Strategic" — that classification is applied by deterministic business rules, not by you.
5. Return ONLY valid JSON matching the exact schema. No prose outside JSON.
6. Consider NWC's context: water treatment, pumping, distribution, and sewage systems in Saudi Arabia.

═══════════════════════════════════════════════════════════
DIMENSION 1 — Operations Criticality
═══════════════════════════════════════════════════════════
A (12 pts) — Complete shutdown / Single Point of Failure
    All conditions must apply: failure stops an entire process AND no redundancy exists
B (10 pts) — Partial shutdown
    Failure significantly degrades operations without fully stopping them
C (3 pts)  — Operations affected but workaround exists
    Impact present but a temporary workaround is feasible
D (0 pts)  — No operational impact
    Failure has no meaningful effect on operations

═══════════════════════════════════════════════════════════
DIMENSION 2 — Water Quality Criticality
═══════════════════════════════════════════════════════════
A (10 pts) — Direct degradation of water or sewage service
    Part is directly involved in water quality control or treatment
B (3 pts)  — Slight degradation
    Indirect impact on water quality is possible
C (0 pts)  — No impact on water quality
    Part has no connection to water quality processes

═══════════════════════════════════════════════════════════
DIMENSION 3 — Availability Criticality
═══════════════════════════════════════════════════════════
A (10 pts) — ALL four conditions apply:
    1. Backup is required
    2. No suitable substitute exists
    3. Procurement lead time exceeds the Time-To-Repair (TTR)
    4. Single manufacturer or single country of origin
B (3 pts)  — At least one approved substitute or equivalent exists
C (0 pts)  — Backup is not required (easily available or operations tolerate absence)

═══════════════════════════════════════════════════════════
DIMENSION 4 — Safety Criticality
═══════════════════════════════════════════════════════════
A (10 pts) — Risk to personnel, environment, or critical infrastructure
    Failure could cause injury, environmental damage, or major asset damage
B (5 pts)  — Partial safety risk under specific failure scenarios
C (0 pts)  — No safety consequences

═══════════════════════════════════════════════════════════
REQUIRED JSON OUTPUT SCHEMA
═══════════════════════════════════════════════════════════
{
  "operations": {
    "selected_option": "A" | "B" | "C" | "D",
    "score": <integer matching the dimension table above>,
    "confidence": <float 0.0–1.0>,
    "reason": "<engineering reasoning citing specific evidence>",
    "sources": ["<URL or document title>", ...]
  },
  "water_quality": {
    "selected_option": "A" | "B" | "C",
    "score": <integer>,
    "confidence": <float>,
    "reason": "<reasoning>",
    "sources": [...]
  },
  "availability": {
    "selected_option": "A" | "B" | "C",
    "score": <integer>,
    "confidence": <float>,
    "reason": "<reasoning>",
    "sources": [...]
  },
  "safety": {
    "selected_option": "A" | "B" | "C",
    "score": <integer>,
    "confidence": <float>,
    "reason": "<reasoning>",
    "sources": [...]
  }
}"""


# ── Evidence formatting helpers ────────────────────────────────────────────────

def _format_evidence(research: ResearchResult, db_attributes: dict) -> str:
    """
    Build the evidence text block sent to the LLM.

    Checks the _evidence_quality marker set by ResearchAgent.
    If quality is 'insufficient', returns an explicit NO-EVIDENCE notice
    instead of empty or unrelated content, so the LLM selects conservative
    options rather than hallucinating based on bad data.
    """
    sections: list[str] = []

    # ── Evidence quality gate ─────────────────────────────────────────────────
    eq_attr = (research.attributes or {}).get("_evidence_quality")
    evidence_quality = getattr(eq_attr, "value", "unknown") if eq_attr else "unknown"
    logger.info("Evidence quality for part '%s': %s", research.part_number, evidence_quality)

    if evidence_quality == "insufficient":
        msg = (
            "⚠️  INSUFFICIENT EVIDENCE\n"
            f"No relevant engineering documentation was found for part '{research.part_number}'.\n"
            "The web search returned no results that specifically match this part number.\n"
            "REQUIRED BEHAVIOUR: Use the LOWEST-RISK option for every dimension. "
            "Set confidence = 0.1 for all dimensions. "
            "State in every reason: 'No engineering evidence found for this part number.'"
        )
        logger.warning("Passing INSUFFICIENT_EVIDENCE notice to LLM for part '%s'", research.part_number)
        return msg

    # ── Web research sources ──────────────────────────────────────────────────
    if research.source_urls:
        src_lines = []
        for s in research.source_urls[:10]:
            title   = s.get("title", "")
            url     = s.get("url", "")
            snippet = s.get("snippet", "")[:300]
            src_lines.append(f"  • [{title}]({url})\n    {snippet}")
        sections.append("WEB RESEARCH SOURCES\n" + "\n".join(src_lines))

    # ── Technical attributes (skip internal markers) ──────────────────────────
    all_attrs: dict[str, dict] = {}
    for name, attr in (research.attributes or {}).items():
        if name.startswith("_"):
            continue
        all_attrs[name] = {
            "value":      getattr(attr, "value", str(attr)),
            "source":     getattr(attr, "source", "Research"),
            "confidence": getattr(attr, "confidence", 0.5),
        }
    for name, attr_dict in (db_attributes or {}).items():
        if name.startswith("_"):
            continue
        existing = all_attrs.get(name, {})
        if attr_dict.get("source_tier", 5) < existing.get("tier", 5):
            all_attrs[name] = {
                "value":      attr_dict.get("value", ""),
                "source":     attr_dict.get("source", "DB"),
                "confidence": attr_dict.get("confidence", 0.7),
            }

    if all_attrs:
        attr_lines = [
            f"  {name.replace('_', ' ').title()}: {d['value']} "
            f"(source: {d['source']}, confidence: {d['confidence']:.0%})"
            for name, d in all_attrs.items()
            if d.get("value")
        ]
        if attr_lines:
            sections.append("EXTRACTED ATTRIBUTES\n" + "\n".join(attr_lines))

    if evidence_quality == "partial":
        sections.append(
            "⚠️  EVIDENCE QUALITY: PARTIAL\n"
            "Only limited relevant sources were found. "
            "Cap all confidence values at 0.6 maximum."
        )

    return "\n\n".join(sections) if sections else "No structured evidence available."



def _format_user_prompt(research: ResearchResult, db_attributes: dict) -> str:
    """Build the user message."""
    evidence = _format_evidence(research, db_attributes)
    return f"""PART INFORMATION
Part Number : {research.part_number}
Part Name   : {research.part_name or "Unknown"}
Description : {research.description or "Not available"}
Manufacturer: {research.manufacturer or "Unknown"}
Part Type   : {research.part_type or "Unknown"}
Tech Specs  : {research.technical_specs or "Not available"}
Country     : {research.country_of_origin or "Unknown"}
OEM Only    : {research.oem_only}
Substitute  : {research.substitute_available}
Obsolescence: {research.obsolescence_risk or "Unknown"}
Supplier    : {research.supplier_info or "Unknown"}

EVIDENCE
{evidence}

Assess each of the four NWC criticality dimensions based on all evidence above.
Remember: insufficient evidence → lowest-risk option + confidence < 0.5.
Return only the JSON response."""


# ── Agent ──────────────────────────────────────────────────────────────────────

class CriticalityAnalysisAgent:
    """
    LLM-powered agent that converts research evidence into structured
    dimension assessments consumed by the NWC scoring engine.
    """

    def __init__(
        self,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self._settings = get_settings()
        self._provider = provider or get_llm_provider(self._settings)

    def analyse(
        self,
        research: ResearchResult,
        db_attributes: Optional[dict] = None,
    ) -> NWCAssessmentResult:
        """
        Run the full analysis pipeline:
          1. Build evidence prompt
          2. Call LLM
          3. Parse structured JSON
          4. Pass to NWC Rule Engine for final scoring and classification
        """
        db_attributes = db_attributes or {}
        inference_start = datetime.now(timezone.utc)

        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user",   content=_format_user_prompt(research, db_attributes)),
        ]

        # ── Full prompt logging (always logged at INFO so it can be reviewed) ─
        full_prompt = (
            f"[SYSTEM]\n{_SYSTEM_PROMPT[:300]}...\n\n"
            f"[USER]\n{messages[1].content}"
        )
        logger.info(
            "=== CriticalityAnalysisAgent PROMPT (part=%r, model=%s/%s) ===\n%s\n=== END PROMPT ===",
            research.part_number,
            self._provider.provider_name,
            self._settings.LLM_MODEL,
            messages[1].content,   # full user message — contains evidence
        )

        logger.info(
            "CriticalityAnalysisAgent: calling LLM (%s/%s) for part '%s'",
            self._provider.provider_name,
            self._settings.LLM_MODEL,
            research.part_number,
        )

        llm_response = self._provider.complete(messages)

        logger.info(
            "=== LLM RAW RESPONSE (part=%r) ===\n%s\n=== END RESPONSE ===",
            research.part_number,
            llm_response.content,
        )

        analysis_input = self._parse_llm_response(llm_response)

        result = calculate_nwc_assessment(
            analysis=analysis_input,
            model_used=f"{self._provider.provider_name}/{llm_response.model}",
            prompt_version=PROMPT_VERSION,
        )

        logger.info(
            "Analysis complete in %.1fs: label=%s score=%d/%d conf=%.0f%%",
            (datetime.now(timezone.utc) - inference_start).total_seconds(),
            result.label,
            result.total_score,
            result.max_score,
            result.overall_confidence * 100,
        )
        return result

    def _parse_llm_response(self, response: LLMResponse) -> CriticalityAnalysisInput:
        """Parse and validate the LLM JSON response."""
        try:
            data = response.parse_json()
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("LLM returned invalid JSON: %s\nContent: %s", exc, response.content[:500])
            return self._fallback_analysis("LLM returned malformed JSON.")

        try:
            return CriticalityAnalysisInput(
                operations=DimensionScore(**data["operations"]),
                water_quality=DimensionScore(**data["water_quality"]),
                availability=DimensionScore(**data["availability"]),
                safety=DimensionScore(**data["safety"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("LLM JSON schema mismatch: %s\nData: %s", exc, str(data)[:500])
            return self._fallback_analysis(f"Schema validation failed: {exc}")

    @staticmethod
    def _fallback_analysis(reason: str) -> CriticalityAnalysisInput:
        """
        Return a conservative (lowest-risk) analysis when the LLM fails.
        Confidence is set to 0 to flag this in the UI.
        """
        logger.warning("Using fallback analysis. Reason: %s", reason)
        fallback = DimensionScore(
            selected_option="D",
            score=0,
            confidence=0.0,
            reason=f"Fallback: {reason} Manual review required.",
            sources=[],
        )
        return CriticalityAnalysisInput(
            operations=DimensionScore(
                selected_option="D", score=0, confidence=0.0,
                reason=f"Fallback — {reason}", sources=[],
            ),
            water_quality=DimensionScore(
                selected_option="C", score=0, confidence=0.0,
                reason=f"Fallback — {reason}", sources=[],
            ),
            availability=DimensionScore(
                selected_option="C", score=0, confidence=0.0,
                reason=f"Fallback — {reason}", sources=[],
            ),
            safety=DimensionScore(
                selected_option="C", score=0, confidence=0.0,
                reason=f"Fallback — {reason}", sources=[],
            ),
        )
