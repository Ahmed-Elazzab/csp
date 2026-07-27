"""Shared data-transfer objects used across agents and pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Source-tier constants (lower = more trusted) ──────────────────────────────
SOURCE_TIER_ERP = 1
SOURCE_TIER_OEM = 2
SOURCE_TIER_DISTRIBUTOR = 3
SOURCE_TIER_WEB = 4
SOURCE_TIER_AI = 5

SOURCE_TIER_LABELS = {
    SOURCE_TIER_ERP: "ERP / Manual Input",
    SOURCE_TIER_OEM: "OEM Datasheet",
    SOURCE_TIER_DISTRIBUTOR: "Approved Supplier / Distributor",
    SOURCE_TIER_WEB: "Public Website",
    SOURCE_TIER_AI: "AI Inference",
}


@dataclass
class AttributeData:
    """Single extracted attribute value with provenance."""

    value: str
    source: str
    source_url: Optional[str] = None
    confidence: float = 0.5
    source_tier: int = SOURCE_TIER_AI


@dataclass
class ResearchResult:
    """Structured output from the ResearchAgent."""

    part_number: str
    part_name: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    part_type: Optional[str] = None
    technical_specs: Optional[str] = None
    country_of_origin: Optional[str] = None
    oem_only: Optional[bool] = None
    substitute_available: Optional[bool] = None
    obsolescence_risk: Optional[str] = None  # low / medium / high
    supplier_info: Optional[str] = None
    # Keyed by normalised attribute name (lower-snake)
    attributes: dict[str, AttributeData] = field(default_factory=dict)
    source_urls: list[dict] = field(default_factory=list)  # {url, title, snippet, tier}
    overall_confidence: float = 0.0
    raw_search_results: list[dict] = field(default_factory=list)

