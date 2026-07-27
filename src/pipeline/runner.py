"""
Autonomous NWC Assessment Pipeline Runner
==========================================

Orchestrates the complete spare-part criticality assessment without any
user intervention.  Progress is reported via callbacks so the UI can
display a live professional execution view.

Pipeline stages:
  1. Validate Input
  2. Research Technical Documentation
  3. Collect Engineering Evidence
  4. Extract Technical Attributes
  5. Run Criticality Analysis Agent (LLM)
  6. Apply NWC Rule Engine (deterministic)
  7. Generate Assessment Report
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Stage status ──────────────────────────────────────────────────────────────

class StageStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


@dataclass
class StageResult:
    name: str
    status: StageStatus
    duration_s: float = 0.0
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Complete output from a single pipeline run."""

    success: bool = False
    part_id: int = 0
    assessment_id: int = 0
    nwc_result: Any = None           # NWCAssessmentResult
    research_result: Any = None      # ResearchResult
    stages: list[StageResult] = field(default_factory=list)
    total_duration_s: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        if self.research_result:
            return len(getattr(self.research_result, "source_urls", []))
        return 0


# ── Progress callback type ─────────────────────────────────────────────────────
# (stage_name: str, status: StageStatus, detail: str, data: dict) -> None
ProgressCallback = Callable[[str, StageStatus, str, dict], None]

STAGE_NAMES = [
    "Validating Input",
    "Researching Technical Documentation",
    "Collecting Engineering Evidence",
    "Extracting Technical Attributes",
    "Running Criticality Analysis Agent",
    "Applying Deterministic NWC Rule Engine",
    "Generating Assessment Report",
]


# ── Pipeline runner ────────────────────────────────────────────────────────────

class AssessmentPipeline:
    """
    Fully autonomous NWC spare-part criticality assessment pipeline.

    The user provides only a part number or description.
    All stages execute without user interaction.
    """

    def __init__(
        self,
        research_agent=None,
        analysis_agent=None,
        db_agent=None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> None:
        # Lazy imports to avoid circular deps at module load time
        from src.agents.research_agent import ResearchAgent
        from src.agents.criticality_analysis_agent import CriticalityAnalysisAgent
        from src.agents.database_agent import DatabaseAgent

        self._research  = research_agent  or ResearchAgent()
        self._analysis  = analysis_agent  or CriticalityAnalysisAgent()
        self._db        = db_agent        or DatabaseAgent()
        self._on_progress = on_progress

    def _progress(
        self,
        name: str,
        status: StageStatus,
        detail: str = "",
        data: dict | None = None,
    ) -> None:
        if self._on_progress:
            try:
                self._on_progress(name, status, detail, data or {})
            except Exception as exc:
                logger.debug("Progress callback error: %s", exc)

    def run(self, part_input: str) -> PipelineResult:
        """
        Execute the full assessment pipeline.

        Errors in individual stages are caught and logged.
        The pipeline always attempts to produce an assessment.
        """
        pipeline_start = time.time()
        result = PipelineResult()

        # ── Stage 1: Validate Input ───────────────────────────────────────────
        s1 = self._run_stage(
            "Validating Input",
            lambda: self._validate(part_input),
            result,
        )
        if s1.status == StageStatus.FAILED:
            result.error = s1.detail
            result.total_duration_s = round(time.time() - pipeline_start, 2)
            return result

        # ── Stage 2: Research ─────────────────────────────────────────────────
        s2 = self._run_stage(
            "Researching Technical Documentation",
            lambda: self._research_part(part_input, result),
            result,
        )

        # ── Stage 3: Persist evidence ─────────────────────────────────────────
        s3 = self._run_stage(
            "Collecting Engineering Evidence",
            lambda: self._persist_evidence(result),
            result,
        )

        # ── Stage 4: Read attributes ──────────────────────────────────────────
        db_attrs: dict = {}
        s4 = self._run_stage(
            "Extracting Technical Attributes",
            lambda: self._extract_attributes(result, db_attrs),
            result,
        )

        # ── Stage 5: AI Analysis ──────────────────────────────────────────────
        s5 = self._run_stage(
            "Running Criticality Analysis Agent",
            lambda: self._run_analysis(result, db_attrs),
            result,
        )

        # ── Stage 6: Rule Engine (applied inside analysis; log only) ─────────
        s6 = self._run_stage(
            "Applying Deterministic NWC Rule Engine",
            lambda: self._log_rule_engine(result),
            result,
        )

        # ── Stage 7: Persist assessment ───────────────────────────────────────
        s7 = self._run_stage(
            "Generating Assessment Report",
            lambda: self._persist_assessment(result),
            result,
        )

        result.success = result.nwc_result is not None
        result.total_duration_s = round(time.time() - pipeline_start, 2)

        logger.info(
            "Pipeline complete: success=%s part_id=%d assessment_id=%d "
            "label=%s total=%.1fs",
            result.success,
            result.part_id,
            result.assessment_id,
            getattr(result.nwc_result, "label", "N/A"),
            result.total_duration_s,
        )
        return result

    # ── Private stage implementations ─────────────────────────────────────────

    def _run_stage(
        self,
        name: str,
        fn: Callable[[], tuple[str, dict]],
        pipeline_result: PipelineResult,
    ) -> StageResult:
        self._progress(name, StageStatus.RUNNING)
        t0 = time.time()
        try:
            detail, data = fn()
            sr = StageResult(
                name=name,
                status=StageStatus.COMPLETED,
                duration_s=round(time.time() - t0, 2),
                detail=detail,
                data=data,
            )
            self._progress(name, StageStatus.COMPLETED, detail, data)
        except Exception as exc:
            logger.warning("Stage '%s' failed: %s", name, exc)
            detail = str(exc)[:200]
            sr = StageResult(
                name=name,
                status=StageStatus.FAILED,
                duration_s=round(time.time() - t0, 2),
                detail=detail,
            )
            pipeline_result.warnings.append(f"{name}: {detail}")
            self._progress(name, StageStatus.FAILED, detail)

        pipeline_result.stages.append(sr)
        return sr

    def _validate(self, part_input: str) -> tuple[str, dict]:
        cleaned = part_input.strip()
        if not cleaned:
            raise ValueError("Part number or description cannot be empty")
        return f"Input accepted: '{cleaned[:60]}'", {"input": cleaned}

    def _research_part(self, part_input: str, pr: PipelineResult) -> tuple[str, dict]:
        research = self._research.research_part(part_input.strip())
        pr.research_result = research
        n_src = len(research.source_urls)
        n_attr = len(research.attributes)
        return (
            f"{n_src} sources found · {n_attr} attributes extracted "
            f"(confidence {research.overall_confidence:.0%})",
            {"sources": n_src, "attributes": n_attr,
             "confidence": research.overall_confidence},
        )

    def _persist_evidence(self, pr: PipelineResult) -> tuple[str, dict]:
        if pr.research_result is None:
            return "Skipped — no research result", {}
        part_id = self._db.upsert_part(pr.research_result)
        self._db.save_part_attributes(part_id, pr.research_result)
        self._db.save_research_sources(part_id, pr.research_result)
        pr.part_id = part_id
        return f"Part ID {part_id} persisted", {"part_id": part_id}

    def _extract_attributes(
        self, pr: PipelineResult, db_attrs_out: dict
    ) -> tuple[str, dict]:
        if not pr.part_id:
            return "Skipped — no part ID", {}
        attrs = self._db.get_part_attributes(pr.part_id)
        db_attrs_out.update(attrs)
        return f"{len(attrs)} attributes available", {"count": len(attrs)}

    def _run_analysis(
        self, pr: PipelineResult, db_attrs: dict
    ) -> tuple[str, dict]:
        nwc = self._analysis.analyse(
            research=pr.research_result,
            db_attributes=db_attrs,
        )
        pr.nwc_result = nwc
        return (
            f"Model: {nwc.model_used} · Confidence: {nwc.overall_confidence:.0%}",
            {"model": nwc.model_used, "confidence": nwc.overall_confidence,
             "prompt_version": nwc.prompt_version},
        )

    def _log_rule_engine(self, pr: PipelineResult) -> tuple[str, dict]:
        if pr.nwc_result is None:
            return "Skipped — no analysis result", {}
        r = pr.nwc_result
        strategic = r.strategic_rules_triggered
        detail = (
            f"Score {r.total_score}/{r.max_score} → **{r.label}**"
            + (f" · {len(strategic)} strategic rule(s) triggered" if strategic else "")
        )
        return detail, {
            "label": r.label,
            "score": r.total_score,
            "strategic_rules": strategic,
        }

    def _persist_assessment(self, pr: PipelineResult) -> tuple[str, dict]:
        if pr.nwc_result is None or not pr.part_id:
            return "Skipped — missing data", {}
        assessment_id = self._db.save_nwc_assessment(
            part_id=pr.part_id,
            nwc_result=pr.nwc_result,
            analysis_json=pr.nwc_result.model_dump_json(),
        )
        pr.assessment_id = assessment_id
        return f"Assessment ID {assessment_id} stored", {"assessment_id": assessment_id}
