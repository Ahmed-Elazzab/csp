"""
Research Agent – Evidence Collection for NWC Spare Part Assessment
===================================================================

Collects engineering evidence from multiple pluggable sources.
The agent is responsible ONLY for evidence collection, never for reasoning.

Evidence Source Plugin Architecture
------------------------------------
Implement `EvidenceSource` to add new retrieval backends without changing ResearchAgent:
  - TavilyEvidenceSource       (AI-native web search)
  - DDGSEvidenceSource         (DuckDuckGo via library)
  - DDGHTMLEvidenceSource      (DuckDuckGo plain-HTTP fallback)
  - SerpAPIEvidenceSource      (Google-backed API)

Future sources can be added without changing ResearchAgent:
  - NWC maintenance manuals
  - SAP Material Master
  - Internal engineering standards
  - Vector databases / RAG systems
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Optional
from urllib.parse import urlparse, quote_plus, parse_qs, urlparse as _up

import requests
from bs4 import BeautifulSoup

from src.config import get_settings
from src.utils.helpers import (
    SOURCE_TIER_DISTRIBUTOR,
    SOURCE_TIER_OEM,
    SOURCE_TIER_WEB,
    AttributeData,
    ResearchResult,
)

logger = logging.getLogger(__name__)


# ── Domain classifications ─────────────────────────────────────────────────────

OEM_DOMAINS: frozenset[str] = frozenset({
    "siemens.com", "abb.com", "schneider-electric.com", "emerson.com",
    "honeywell.com", "rockwellautomation.com", "yokogawa.com", "endress.com",
    "parker.com", "swagelok.com", "flowserve.com", "pentair.com",
    "grundfos.com", "sulzer.com", "wika.com", "ksb.com", "weir.com",
    "itt.com", "goulds.com", "flygt.com", "xylem.com",
})

DISTRIBUTOR_DOMAINS: frozenset[str] = frozenset({
    "rs-online.com", "rscomponents.com", "digikey.com", "mouser.com",
    "grainger.com", "mscdirect.com", "mcmaster.com", "farnell.com",
    "element14.com", "automation24.com", "directindustry.com",
})

# Domains that MUST NEVER appear in spare-part evidence
_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    # Social media
    "youtube.com", "youtu.be", "facebook.com", "fb.com",
    "twitter.com", "x.com", "instagram.com", "tiktok.com",
    "reddit.com", "pinterest.com", "quora.com", "linkedin.com",
    # Consumer e-commerce (not industrial suppliers)
    "ebay.com", "amazon.com", "aliexpress.com", "alibaba.com",
    # AI/LLM service documentation (not engineering parts)
    "openai.com", "platform.openai.com", "docs.openai.com",
    "anthropic.com", "docs.anthropic.com",
    "ai.google.dev", "cloud.google.com",
    # General encyclopedias / non-technical references
    "wikipedia.org", "britannica.com", "britannica.co.uk",
    "encyclopedia.com", "wikihow.com", "wikimedia.org",
    # Historical / political / news (often false-positive for part-number prefixes)
    "history.com", "historynet.com",
    "bbc.com", "bbc.co.uk", "cnn.com", "reuters.com",
    "nytimes.com", "theguardian.com", "washingtonpost.com",
})

_SITE_EXCL = (
    "-site:youtube.com -site:facebook.com -site:twitter.com "
    "-site:x.com -site:reddit.com -site:wikipedia.org "
    "-site:britannica.com -site:openai.com"
)


# ── Evidence quality helpers ───────────────────────────────────────────────────

def _extract_part_tokens(part_query: str) -> set[str]:
    """
    Extract significant alphanumeric tokens from a part query.
    These are used to score relevance of search results.

    Examples:
        "SS-1F0-3GC"      → {"SS", "1F0", "3GC"}
        "3RV2011-1AA10"   → {"3RV2011", "1AA10"}
        "Pump Seal Kit"   → {"Pump", "Seal", "Kit"}
    """
    # Split on non-alphanumeric characters
    raw = re.split(r'[^a-zA-Z0-9]+', part_query.strip())
    # Keep tokens that are meaningful (len >= 2, not pure common words)
    _STOPWORDS = frozenset({"the", "a", "an", "of", "for", "in", "to",
                             "and", "or", "with", "by", "is", "at"})
    tokens = {t.upper() for t in raw if len(t) >= 2 and t.lower() not in _STOPWORDS}
    return tokens


def _score_relevance(part_tokens: set[str], hit: dict) -> float:
    """
    Score how relevant a search result is to the part query.
    Returns 0.0 (unrelated) to 1.0 (highly relevant).

    A result is relevant if it contains the specific tokens that make up
    the part number/description.
    """
    if not part_tokens:
        return 0.5  # Can't assess without tokens

    text = (hit.get("title", "") + " " + hit.get("body", "")).upper()
    matches = sum(1 for t in part_tokens if t in text)
    return matches / len(part_tokens)


def _filter_results(part_query: str, hits: list[dict]) -> tuple[list[dict], str]:
    """
    Filter search results by:
      1. Domain blocklist (social media, encyclopedias, AI service docs, news)
      2. Relevance score (must contain part number tokens)

    Returns (filtered_hits, evidence_quality) where quality is
    "good" | "partial" | "insufficient".
    """
    if not hits:
        return [], "insufficient"

    part_tokens = _extract_part_tokens(part_query)
    logger.debug(
        "Evidence filter — part_query=%r tokens=%s candidates=%d",
        part_query, part_tokens, len(hits)
    )

    # ── Step 1: Domain blocklist ──────────────────────────────────────────────
    domain_passed: list[dict] = []
    for h in hits:
        try:
            host = urlparse(h.get("href", "")).netloc.lstrip("www.").lower()
            if any(host == d or host.endswith("." + d) for d in _BLOCKED_DOMAINS):
                logger.debug("  BLOCKED domain: %s — %s", host, h.get("title", "")[:60])
                continue
        except Exception:
            pass
        domain_passed.append(h)

    logger.debug("  After domain filter: %d/%d results remain", len(domain_passed), len(hits))

    if not domain_passed:
        return [], "insufficient"

    # ── Step 2: Relevance scoring ─────────────────────────────────────────────
    scored: list[tuple[float, dict]] = []
    for h in domain_passed:
        score = _score_relevance(part_tokens, h)
        scored.append((score, h))
        logger.debug(
            "  Relevance %.2f — %s — %s",
            score, urlparse(h.get("href", "")).netloc[:40], h.get("title", "")[:60]
        )

    scored.sort(key=lambda x: -x[0])

    # Separate into relevant and potentially irrelevant
    RELEVANCE_THRESHOLD = 0.25  # at least 25% of part tokens must appear
    relevant    = [(s, h) for s, h in scored if s >= RELEVANCE_THRESHOLD]
    irrelevant  = [(s, h) for s, h in scored if s < RELEVANCE_THRESHOLD]

    logger.info(
        "Evidence relevance — part=%r tokens=%s relevant=%d irrelevant=%d",
        part_query[:40], part_tokens, len(relevant), len(irrelevant)
    )

    if irrelevant:
        for s, h in irrelevant:
            logger.warning(
                "IRRELEVANT result filtered (score=%.2f): %s — %s",
                s, h.get("href", "")[:80], h.get("title", "")[:60]
            )

    if relevant:
        # Good: at least some results are relevant
        quality = "good" if len(relevant) >= 3 else "partial"
        return [h for _, h in relevant], quality

    # No relevant results — log clearly and return a warning
    logger.error(
        "NO RELEVANT EVIDENCE for part '%s'. "
        "Top domains returned by search: %s. "
        "These results will NOT be passed to the LLM.",
        part_query,
        [urlparse(h.get("href", "")).netloc for _, h in scored[:5]],
    )
    return [], "insufficient"


def _classify_url_tier(url: str) -> int:
    try:
        host = urlparse(url).netloc.lstrip("www.").lower()
        if any(host.endswith(d) for d in OEM_DOMAINS):
            return SOURCE_TIER_OEM
        if any(host.endswith(d) for d in DISTRIBUTOR_DOMAINS):
            return SOURCE_TIER_DISTRIBUTOR
    except Exception:
        pass
    return SOURCE_TIER_WEB


# ── EvidenceSource plugin interface ───────────────────────────────────────────

class EvidenceSource(ABC):
    """
    Abstract base for evidence collection backends.
    Subclass this to add new retrieval sources without modifying ResearchAgent.
    """

    @abstractmethod
    def collect(self, query: str, max_results: int) -> list[dict]:
        """
        Collect evidence items.
        Returns list of {href, title, body} dicts.
        Never raises — returns [] on any failure.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...

    @property
    def trust_tier(self) -> int:
        return SOURCE_TIER_WEB

    @classmethod
    def is_configured(cls, settings) -> bool:
        return True


# ── Concrete source implementations ───────────────────────────────────────────

class TavilyEvidenceSource(EvidenceSource):
    """
    Tavily AI-native search — recommended for industrial/technical content.
    Uses exact part number as primary search term, context only as secondary.
    """

    def __init__(self, settings) -> None:
        self._s = settings

    @classmethod
    def is_configured(cls, settings) -> bool:
        return bool(settings.TAVILY_API_KEY)

    @property
    def source_name(self) -> str:
        return "Tavily"

    def collect(self, query: str, max_results: int) -> list[dict]:
        try:
            from tavily import TavilyClient  # type: ignore
            client = TavilyClient(api_key=self._s.TAVILY_API_KEY)

            # Primary: exact part number with engineering context (NOT too many generic terms)
            primary_query = f"{query} technical datasheet specifications"
            logger.info("[Tavily] Sending query: %r", primary_query)

            resp = client.search(
                query=primary_query,
                search_depth="advanced",
                max_results=max_results * 2,
                include_answer=False,
            )
            hits = [
                {
                    "href":  r.get("url", ""),
                    "title": r.get("title", ""),
                    "body":  r.get("content", ""),
                }
                for r in resp.get("results", []) if r.get("url")
            ]
            logger.info("[Tavily] Raw results: %d", len(hits))
            for h in hits:
                logger.debug("  [Tavily] %s — %s", h["href"][:80], h["title"][:60])
            return hits
        except ImportError:
            logger.warning("tavily-python not installed — run: pip install tavily-python")
            return []
        except Exception as exc:
            logger.warning("[Tavily] Search failed: %s", exc)
            return []


class DDGSEvidenceSource(EvidenceSource):
    """DuckDuckGo via duckduckgo-search library."""

    def __init__(self, settings) -> None:
        self._s = settings

    @property
    def source_name(self) -> str:
        return "DuckDuckGo (DDGS)"

    def collect(self, query: str, max_results: int) -> list[dict]:
        # Try quoted exact match first, then broader fallback
        query_sets = [
            [f'"{query}" technical datasheet {_SITE_EXCL}'],
            [f'"{query}" spare part {_SITE_EXCL}'],
            [f'{query} industrial technical {_SITE_EXCL}'],
        ]
        for queries in query_sets:
            hits: list[dict] = []
            seen: set[str] = set()
            for attempt in range(2):
                try:
                    from duckduckgo_search import DDGS  # type: ignore
                    with DDGS() as ddgs:
                        for q in queries:
                            logger.info("[DDGS] Sending query: %r", q)
                            for r in ddgs.text(q, max_results=max_results):
                                href = r.get("href", "")
                                if href and href not in seen:
                                    seen.add(href)
                                    hits.append(r)
                                    logger.debug("  [DDGS] %s — %s", href[:80], r.get("title", "")[:60])
                            time.sleep(0.8)
                    if hits:
                        return hits[:max_results * 2]
                except Exception as exc:
                    wait = 1.5 ** attempt
                    logger.warning("[DDGS] Attempt %d failed: %s — retrying in %.1fs", attempt + 1, exc, wait)
                    time.sleep(wait)
        return []


class DDGHTMLEvidenceSource(EvidenceSource):
    """DuckDuckGo plain-HTTP endpoint — more WSL/corporate-network friendly."""

    def __init__(self, settings) -> None:
        self._s = settings

    @property
    def source_name(self) -> str:
        return "DuckDuckGo (HTML)"

    def collect(self, query: str, max_results: int) -> list[dict]:
        full_query = f'"{query}" technical datasheet {_SITE_EXCL}'
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(full_query)}&ia=web"
        logger.info("[DDG-HTML] Sending query: %r", full_query)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            hits: list[dict] = []
            for result in soup.select(".result")[:max_results * 2]:
                link_el = result.select_one(".result__a")
                snippet_el = result.select_one(".result__snippet")
                if not link_el:
                    continue
                href = link_el.get("href", "")
                if href.startswith("/"):
                    qs = parse_qs(_up(href).query)
                    href = qs.get("uddg", [href])[0]
                if not href.startswith("http"):
                    continue
                hits.append({
                    "title": link_el.get_text(strip=True),
                    "href": href,
                    "body": snippet_el.get_text(strip=True) if snippet_el else "",
                })
                logger.debug("  [DDG-HTML] %s — %s", href[:80], link_el.get_text(strip=True)[:60])
            logger.info("[DDG-HTML] Raw results: %d", len(hits))
            return hits
        except Exception as exc:
            logger.warning("[DDG-HTML] Failed: %s", exc)
            return []


class SerpAPIEvidenceSource(EvidenceSource):
    """SerpAPI Google-backed search."""

    def __init__(self, settings) -> None:
        self._s = settings

    @classmethod
    def is_configured(cls, settings) -> bool:
        return bool(settings.SERPAPI_KEY)

    @property
    def source_name(self) -> str:
        return "SerpAPI"

    def collect(self, query: str, max_results: int) -> list[dict]:
        q = f'"{query}" technical datasheet {_SITE_EXCL}'
        logger.info("[SerpAPI] Sending query: %r", q)
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params={"q": q, "api_key": self._s.SERPAPI_KEY,
                        "num": max_results * 2, "hl": "en"},
                timeout=10,
            )
            resp.raise_for_status()
            hits = [
                {"href": r.get("link", ""), "title": r.get("title", ""), "body": r.get("snippet", "")}
                for r in resp.json().get("organic_results", [])
            ]
            logger.info("[SerpAPI] Raw results: %d", len(hits))
            return hits
        except Exception as exc:
            logger.warning("[SerpAPI] Failed: %s", exc)
            return []


# ── ResearchAgent ──────────────────────────────────────────────────────────────

class ResearchAgent:
    """
    Collects engineering evidence for a spare part using configured sources.

    Evidence collection flow:
      1. Try each source in priority order until relevant results found
      2. Apply domain blocklist (social media, encyclopedias, AI services, news)
      3. Apply relevance scoring (must contain part-number tokens)
      4. Return evidence quality indicator alongside results
    """

    def __init__(self, sources: Optional[list[EvidenceSource]] = None) -> None:
        self._settings = get_settings()
        self._sources = sources if sources is not None else self._build_default_sources()
        self._openai_client = None

        if self._settings.effective_llm_api_key and self._settings.LLM_PROVIDER in (
            "openai", "azure_openai", "ollama", "openai_compatible", "lmstudio", "vllm"
        ):
            try:
                from openai import OpenAI  # type: ignore
                self._openai_client = OpenAI(
                    api_key=self._settings.effective_llm_api_key,
                    base_url=self._settings.LLM_BASE_URL or None,
                    timeout=30,
                    max_retries=1,
                )
                logger.debug("Research extraction LLM client ready")
            except Exception as exc:
                logger.debug("Research LLM client unavailable: %s", exc)

    def _build_default_sources(self) -> list[EvidenceSource]:
        settings = self._settings
        sources: list[EvidenceSource] = []
        if TavilyEvidenceSource.is_configured(settings):
            sources.append(TavilyEvidenceSource(settings))
        sources.append(DDGSEvidenceSource(settings))
        sources.append(DDGHTMLEvidenceSource(settings))
        if SerpAPIEvidenceSource.is_configured(settings):
            sources.append(SerpAPIEvidenceSource(settings))
        logger.info(
            "ResearchAgent sources: %s",
            [s.source_name for s in sources],
        )
        return sources

    def research_part(self, part_number: str) -> ResearchResult:
        """
        Collect engineering evidence for a spare part.
        
        Returns a ResearchResult with:
        - source_urls: only relevant, domain-filtered, relevance-scored results
        - attributes: extracted structured data
        - overall_confidence: quality indicator
        - evidence_quality: "good" | "partial" | "insufficient"
        """
        logger.info(
            "=== ResearchAgent.research_part START: input=%r ===",
            part_number,
        )
        result = ResearchResult(part_number=part_number)

        raw_hits, evidence_quality = self._collect_evidence(part_number)

        logger.info(
            "Evidence collection complete: %d relevant hits, quality=%s",
            len(raw_hits), evidence_quality,
        )

        # Populate source_urls ONLY from relevant, filtered hits
        seen_urls: set[str] = set()
        for hit in raw_hits:
            url = hit.get("href", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                tier = _classify_url_tier(url)
                result.source_urls.append({
                    "url": url,
                    "title": hit.get("title", ""),
                    "snippet": hit.get("body", "")[:300],
                    "tier": tier,
                })
                logger.debug("Accepted source: [tier=%d] %s — %s", tier, url[:70], hit.get("title", "")[:60])

        # Store quality indicator for downstream use
        result.raw_search_results = raw_hits

        if evidence_quality == "insufficient" or not raw_hits:
            logger.warning(
                "INSUFFICIENT EVIDENCE for part '%s'. "
                "LLM will receive explicit notice of missing evidence.",
                part_number,
            )
            result.overall_confidence = 0.05
            # Store quality marker in attributes for downstream agents
            result.attributes["_evidence_quality"] = AttributeData(
                value="insufficient",
                source="ResearchAgent",
                confidence=0.0,
                source_tier=5,
            )
            return result

        # Extract structured attributes
        if self._openai_client:
            extracted = self._extract_with_llm(part_number, raw_hits)
        else:
            extracted = self._extract_heuristic(part_number, raw_hits)

        self._populate_result(result, extracted, raw_hits, evidence_quality)
        result.attributes["_evidence_quality"] = AttributeData(
            value=evidence_quality,
            source="ResearchAgent",
            confidence=1.0 if evidence_quality == "good" else 0.6,
            source_tier=5,
        )
        logger.info(
            "=== ResearchAgent.research_part END: part=%r sources=%d confidence=%.0f%% ===",
            part_number, len(result.source_urls), result.overall_confidence * 100,
        )
        return result

    # ── Evidence collection ───────────────────────────────────────────────────

    def _collect_evidence(self, part_number: str) -> tuple[list[dict], str]:
        """
        Try each source in priority order; apply domain + relevance filtering.
        Returns (filtered_hits, evidence_quality).
        """
        timeout = self._settings.SEARCH_TIMEOUT
        max_results = self._settings.SEARCH_MAX_RESULTS

        def _run() -> tuple[list[dict], str]:
            for source in self._sources:
                logger.info("Trying evidence source: %s", source.source_name)
                try:
                    raw = source.collect(part_number, max_results)
                except Exception as exc:
                    logger.warning("Source %s raised unexpectedly: %s", source.source_name, exc)
                    raw = []

                if not raw:
                    logger.info("  → No raw results from %s", source.source_name)
                    continue

                filtered, quality = _filter_results(part_number, raw)
                logger.info(
                    "  → %s: %d raw → %d filtered (quality=%s)",
                    source.source_name, len(raw), len(filtered), quality,
                )
                if filtered:
                    return filtered[:max_results * 2], quality

            logger.warning("All sources exhausted — no relevant evidence for '%s'", part_number)
            return [], "insufficient"

        if timeout <= 0:
            return _run()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeout:
                logger.error(
                    "Evidence collection timed out after %ds for '%s'",
                    timeout, part_number,
                )
                return [], "insufficient"

    # ── LLM extraction ────────────────────────────────────────────────────────

    def _extract_with_llm(self, part_number: str, hits: list[dict]) -> dict[str, Any]:
        """Use LLM to extract structured part attributes from search snippets."""
        combined = "\n\n".join(
            f"Source: {h.get('href', '')}\nTitle: {h.get('title', '')}\n"
            f"Content: {h.get('body', '')[:600]}"
            for h in hits[:6]
        )
        prompt = (
            f"Extract spare-part information for part number: {part_number}\n\n"
            f"Evidence:\n{combined}\n\n"
            "Return JSON with these keys (null if not found in evidence — do NOT invent facts):\n"
            '{"part_name":null,"description":null,"manufacturer":null,'
            '"model_number":null,"part_type":null,"technical_specs":null,'
            '"typical_usage":null,"supplier_info":null,"country_of_origin":null,'
            '"oem_only":null,"substitute_available":null,'
            '"obsolescence_risk":null,"confidence":0.0}'
        )
        logger.debug("[Research LLM Extract] Prompt:\n%s", prompt[:800])
        try:
            resp = self._openai_client.chat.completions.create(
                model=self._settings.LLM_MODEL,
                messages=[
                    {"role": "system",
                     "content": "Extract only facts found in the provided evidence. "
                                "Return only valid JSON. Never invent information."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw_resp = resp.choices[0].message.content or "{}"
            logger.debug("[Research LLM Extract] Raw response: %s", raw_resp[:400])
            return json.loads(raw_resp)
        except Exception as exc:
            logger.warning("[Research LLM Extract] Failed: %s — using heuristic", exc)
            return self._extract_heuristic(part_number, hits)

    # ── Heuristic extraction ──────────────────────────────────────────────────

    def _extract_heuristic(self, part_number: str, hits: list[dict]) -> dict[str, Any]:
        """Regex-based extraction when LLM is unavailable."""
        combined = " ".join(f"{h.get('title', '')} {h.get('body', '')}" for h in hits).lower()
        best_title = hits[0].get("title", part_number) if hits else part_number

        manufacturer = None
        for pat in [
            r"\b([A-Z][a-zA-Z]+(?:[\s][A-Z][a-zA-Z]+)*)\s+(?:part|spare|fitting|valve|pump|motor|sensor)\b",
            r"\bby\s+([A-Z][a-zA-Z\s&]+(?:Inc|Ltd|Corp|GmbH|AG|Co)?)[\.,]",
        ]:
            for hit in hits:
                m = re.search(pat, hit.get("title", "") + " " + hit.get("body", ""))
                if m:
                    manufacturer = m.group(1).strip()
                    break
            if manufacturer:
                break

        oem_only = True if "oem only" in combined else (False if "aftermarket" in combined else None)
        obs_risk = "high" if "discontinued" in combined or "obsolete" in combined else (
                   "medium" if "end of life" in combined else None)

        return {
            "part_name": best_title[:120],
            "description": hits[0].get("body", "")[:400] if hits else None,
            "manufacturer": manufacturer,
            "model_number": part_number,
            "part_type": None,
            "technical_specs": None,
            "typical_usage": None,
            "supplier_info": None,
            "country_of_origin": None,
            "oem_only": oem_only,
            "substitute_available": None,
            "obsolescence_risk": obs_risk,
            "confidence": 0.35 if hits else 0.05,
        }

    # ── Result population ─────────────────────────────────────────────────────

    def _populate_result(
        self,
        result: ResearchResult,
        extracted: dict,
        hits: list[dict],
        evidence_quality: str,
    ) -> None:
        conf = float(extracted.get("confidence") or 0.4)

        def _str(val: Any) -> Optional[str]:
            """Ensure a value from LLM extraction is a plain string or None."""
            if val is None:
                return None
            if isinstance(val, str):
                return val or None
            # LLM sometimes returns a dict or list — stringify it
            return str(val)

        result.part_name            = _str(extracted.get("part_name"))
        result.description          = _str(extracted.get("description"))
        result.manufacturer         = _str(extracted.get("manufacturer"))
        result.model_number         = _str(extracted.get("model_number"))
        result.part_type            = _str(extracted.get("part_type"))
        result.technical_specs      = _str(extracted.get("technical_specs"))
        result.country_of_origin    = _str(extracted.get("country_of_origin"))
        result.oem_only             = extracted.get("oem_only")
        result.substitute_available = extracted.get("substitute_available")
        result.obsolescence_risk    = _str(extracted.get("obsolescence_risk"))
        result.supplier_info        = _str(extracted.get("supplier_info"))
        result.overall_confidence   = conf if evidence_quality != "insufficient" else 0.05

        best_url: Optional[str] = None
        best_tier = 99
        for src in result.source_urls:
            if src["tier"] < best_tier:
                best_tier = src["tier"]
                best_url = src["url"]

        src_label = f"Web ({best_tier})"

        def _attr(name: str, val: Any) -> None:
            if val is not None:
                result.attributes[name] = AttributeData(
                    value=str(val), source=src_label,
                    source_url=best_url, confidence=conf, source_tier=best_tier,
                )

        _attr("oem_only_requirement",             result.oem_only)
        _attr("approved_substitute_availability", result.substitute_available)
        _attr("obsolescence_risk",                result.obsolescence_risk)
        if best_tier <= SOURCE_TIER_DISTRIBUTOR:
            _attr("local_presence_distributor_availability", "local")
