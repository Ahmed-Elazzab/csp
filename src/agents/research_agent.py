"""
Research Agent – searches the web for a spare part and extracts structured attributes.

Prioritised source tiers:
  1 = ERP / Manual input (not handled here)
  2 = OEM datasheet
  3 = Approved distributor / supplier
  4 = Public website
  5 = AI inference

When an OpenAI API key is configured the agent uses GPT to parse search snippets
into structured JSON.  Without a key it falls back to heuristic extraction.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import get_settings
from src.utils.helpers import (
    SOURCE_TIER_AI,
    SOURCE_TIER_DISTRIBUTOR,
    SOURCE_TIER_OEM,
    SOURCE_TIER_WEB,
    AttributeData,
    ResearchResult,
)

logger = logging.getLogger(__name__)

# Known OEM / manufacturer domains → tier 2
OEM_DOMAINS: set[str] = {
    "siemens.com", "abb.com", "schneider-electric.com", "emerson.com",
    "honeywell.com", "rockwellautomation.com", "yokogawa.com", "endress.com",
    "parker.com", "swagelok.com", "flowserve.com", "pentair.com",
    "grundfos.com", "sulzer.com", "wika.com",
}

# Known distributor domains → tier 3
DISTRIBUTOR_DOMAINS: set[str] = {
    "rs-online.com", "rscomponents.com", "digikey.com", "mouser.com",
    "grainger.com", "mscdirect.com", "mcmaster.com", "farnell.com",
    "element14.com", "automation24.com", "directindustry.com",
}


def _classify_url_tier(url: str) -> int:
    try:
        host = urlparse(url).netloc.lstrip("www.")
        if any(host.endswith(d) for d in OEM_DOMAINS):
            return SOURCE_TIER_OEM
        if any(host.endswith(d) for d in DISTRIBUTOR_DOMAINS):
            return SOURCE_TIER_DISTRIBUTOR
    except Exception:
        pass
    return SOURCE_TIER_WEB


def _safe_get(url: str, timeout: int = 8) -> Optional[str]:
    """Fetch page text; return None on error."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; CSP-Research-Bot/1.0; "
            "+https://github.com/csp-assessment)"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:4000]
    except Exception as exc:
        logger.debug("Fetch failed %s: %s", url, exc)
        return None


class ResearchAgent:
    """Searches the web for a spare part and returns structured ResearchResult."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._openai_client = None
        if self.settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI  # type: ignore

                self._openai_client = OpenAI(
                    api_key=self.settings.OPENAI_API_KEY,
                    base_url=self.settings.OPENAI_BASE_URL,
                )
                logger.info("ResearchAgent: OpenAI client ready (%s)", self.settings.OPENAI_MODEL)
            except Exception as exc:
                logger.warning("OpenAI init failed: %s", exc)

    # ── Public entry point ────────────────────────────────────────────────────

    def research_part(self, part_number: str) -> ResearchResult:
        """Run the full research pipeline for a part number."""
        result = ResearchResult(part_number=part_number)

        search_hits = self._web_search(part_number)
        result.raw_search_results = search_hits

        # Deduplicate and classify sources
        for hit in search_hits:
            tier = _classify_url_tier(hit.get("href", ""))
            result.source_urls.append(
                {
                    "url": hit.get("href", ""),
                    "title": hit.get("title", ""),
                    "snippet": hit.get("body", "")[:300],
                    "tier": tier,
                }
            )

        if not search_hits:
            logger.warning("No search results for part %s", part_number)
            return result

        if self._openai_client:
            extracted = self._extract_with_openai(part_number, search_hits)
        else:
            extracted = self._extract_heuristic(part_number, search_hits)

        self._populate_result(result, extracted, search_hits)
        return result

    # ── Web search (multi-strategy with fallbacks) ────────────────────────────

    def _web_search(self, part_number: str) -> list[dict]:
        """
        Try three search strategies in order until one returns results:
          1. DuckDuckGo DDGS library  (most capable, but rate-limited in WSL/cloud)
          2. DuckDuckGo HTML endpoint (plain HTTP, bypasses JS-based blocking)
          3. SerpAPI                  (reliable paid/free API – set SERPAPI_KEY in .env)
        """
        hits = self._search_duckduckgo_ddgs(part_number)
        if hits:
            return hits

        logger.info("DDGS returned no results – trying HTML fallback")
        hits = self._search_duckduckgo_html(part_number)
        if hits:
            return hits

        if self.settings.SERPAPI_KEY:
            logger.info("HTML fallback empty – trying SerpAPI")
            hits = self._search_serpapi(part_number)

        if not hits:
            logger.warning(
                "All search strategies returned no results for '%s'. "
                "Check network connectivity in WSL (try: curl https://html.duckduckgo.com). "
                "Set SERPAPI_KEY in .env for a reliable alternative.",
                part_number,
            )
        return hits

    def _search_duckduckgo_ddgs(self, part_number: str) -> list[dict]:
        """DuckDuckGo via the duckduckgo-search library with retry + backoff."""
        # Try two query forms: quoted (exact) first, then unquoted (broader)
        query_sets = [
            [
                f'"{part_number}" spare part specification',
                f'"{part_number}" manufacturer datasheet',
            ],
            [
                f"{part_number} spare part technical",
                f"{part_number} manufacturer",
            ],
        ]
        for queries in query_sets:
            hits: list[dict] = []
            seen: set[str] = set()
            for attempt in range(3):
                try:
                    from duckduckgo_search import DDGS  # type: ignore

                    with DDGS() as ddgs:
                        for q in queries:
                            for r in ddgs.text(
                                q,
                                max_results=self.settings.SEARCH_MAX_RESULTS,
                            ):
                                href = r.get("href", "")
                                if href and href not in seen:
                                    seen.add(href)
                                    hits.append(r)
                            time.sleep(1.0)
                    if hits:
                        logger.info(
                            "DDGS returned %d hits on attempt %d", len(hits), attempt + 1
                        )
                        return hits[: self.settings.SEARCH_MAX_RESULTS * 2]
                except Exception as exc:
                    wait = 2 ** attempt
                    logger.warning(
                        "DDGS attempt %d/%d failed (%s) – retrying in %ds",
                        attempt + 1, 3, exc, wait,
                    )
                    time.sleep(wait)
        return []

    def _search_duckduckgo_html(self, part_number: str) -> list[dict]:
        """
        Parse DuckDuckGo's lightweight HTML endpoint directly.
        More WSL-friendly: plain HTTP GET, no JS, no Cloudflare challenge.
        """
        from urllib.parse import quote_plus

        query = f"{part_number} spare part technical specifications manufacturer"
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            hits: list[dict] = []
            for result in soup.select(".result")[: self.settings.SEARCH_MAX_RESULTS * 2]:
                link_el = result.select_one(".result__a")
                snippet_el = result.select_one(".result__snippet")
                if not link_el:
                    continue
                href = link_el.get("href", "")
                # DDG HTML wraps URLs in a redirect – unwrap if needed
                if href.startswith("/"):
                    from urllib.parse import parse_qs, urlparse as _up
                    qs = parse_qs(_up(href).query)
                    href = qs.get("uddg", [href])[0]
                if not href.startswith("http"):
                    continue
                hits.append(
                    {
                        "title": link_el.get_text(strip=True),
                        "href": href,
                        "body": snippet_el.get_text(strip=True) if snippet_el else "",
                    }
                )
            logger.info("DDG HTML fallback returned %d hits", len(hits))
            return hits
        except Exception as exc:
            logger.warning("DDG HTML fallback failed: %s", exc)
            return []

    def _search_serpapi(self, part_number: str) -> list[dict]:
        """Use SerpAPI (Google Search) when DuckDuckGo is unavailable."""
        try:
            url = "https://serpapi.com/search"
            params = {
                "q": f"{part_number} spare part technical specification manufacturer",
                "api_key": self.settings.SERPAPI_KEY,
                "num": self.settings.SEARCH_MAX_RESULTS * 2,
                "hl": "en",
            }
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            hits: list[dict] = []
            for r in data.get("organic_results", []):
                hits.append(
                    {
                        "title": r.get("title", ""),
                        "href": r.get("link", ""),
                        "body": r.get("snippet", ""),
                    }
                )
            logger.info("SerpAPI returned %d hits", len(hits))
            return hits
        except Exception as exc:
            logger.warning("SerpAPI search failed: %s", exc)
            return []

    # ── OpenAI extraction ─────────────────────────────────────────────────────

    def _extract_with_openai(
        self, part_number: str, hits: list[dict]
    ) -> dict[str, Any]:
        """Use OpenAI to parse search snippets into structured attributes."""
        combined = "\n\n".join(
            f"Source: {h.get('href','')}\nTitle: {h.get('title','')}\nSnippet: {h.get('body','')[:600]}"
            for h in hits[:6]
        )
        system_msg = (
            "You are a spare-parts information extraction assistant. "
            "Return ONLY valid JSON – no markdown, no extra text."
        )
        user_msg = f"""Extract spare-part information for part number: {part_number}

Search results:
{combined}

Return JSON with these keys (use null if unknown):
{{
  "part_name": "string",
  "description": "string",
  "manufacturer": "string",
  "model_number": "string",
  "part_type": "type/category e.g. pump, valve, motor, sensor",
  "technical_specs": "key technical specs as plain text",
  "typical_usage": "string",
  "supplier_info": "string",
  "country_of_origin": "string",
  "oem_only": true/false/null,
  "substitute_available": true/false/null,
  "obsolescence_risk": "low/medium/high or null",
  "confidence": 0.0-1.0,
  "notes": "any other relevant info"
}}"""
        try:
            resp = self._openai_client.chat.completions.create(
                model=self.settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content
            return json.loads(raw)
        except Exception as exc:
            logger.error("OpenAI extraction failed: %s", exc)
            return self._extract_heuristic(part_number, hits)

    # ── Heuristic fallback ────────────────────────────────────────────────────

    def _extract_heuristic(
        self, part_number: str, hits: list[dict]
    ) -> dict[str, Any]:
        """Regex-based extraction when OpenAI is unavailable."""
        combined_text = " ".join(
            f"{h.get('title', '')} {h.get('body', '')}" for h in hits
        ).lower()
        titles = [h.get("title", "") for h in hits]
        best_title = titles[0] if titles else part_number

        # Try to extract manufacturer from title/snippets
        manufacturer = None
        mfr_patterns = [
            r"by\s+([A-Z][a-zA-Z\s&]+(?:Inc|Ltd|Corp|GmbH|AG|Co)?)",
            r"([A-Z][a-zA-Z]+)\s+(?:part|spare|component|model)",
        ]
        for hit in hits:
            for pat in mfr_patterns:
                m = re.search(pat, hit.get("title", "") + " " + hit.get("body", ""))
                if m:
                    manufacturer = m.group(1).strip()
                    break
            if manufacturer:
                break

        # OEM-only hints
        oem_only = None
        if "oem only" in combined_text or "genuine oem" in combined_text:
            oem_only = True
        elif "aftermarket" in combined_text or "compatible" in combined_text:
            oem_only = False

        # Obsolescence
        obs_risk = None
        if "discontinued" in combined_text or "obsolete" in combined_text:
            obs_risk = "high"
        elif "end of life" in combined_text or "eol" in combined_text:
            obs_risk = "medium"

        confidence = 0.35 if hits else 0.0

        return {
            "part_name": best_title[:120] if best_title else part_number,
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
            "confidence": confidence,
            "notes": None,
        }

    # ── Result population ─────────────────────────────────────────────────────

    def _populate_result(
        self,
        result: ResearchResult,
        extracted: dict[str, Any],
        hits: list[dict],
    ) -> None:
        confidence = float(extracted.get("confidence") or 0.4)

        result.part_name = extracted.get("part_name")
        result.description = extracted.get("description")
        result.manufacturer = extracted.get("manufacturer")
        result.model_number = extracted.get("model_number")
        result.part_type = extracted.get("part_type")
        result.technical_specs = extracted.get("technical_specs")
        result.country_of_origin = extracted.get("country_of_origin")
        result.oem_only = extracted.get("oem_only")
        result.substitute_available = extracted.get("substitute_available")
        result.obsolescence_risk = extracted.get("obsolescence_risk")
        result.supplier_info = extracted.get("supplier_info")
        result.overall_confidence = confidence

        # Identify best source URL (prefer highest tier = lowest number)
        best_url: Optional[str] = None
        best_tier = 99
        for src in result.source_urls:
            if src["tier"] < best_tier:
                best_tier = src["tier"]
                best_url = src["url"]

        src_label = f"Web search (tier {best_tier})"
        tier = best_tier

        def _attr(name: str, val: Any) -> None:
            if val is not None:
                result.attributes[name] = AttributeData(
                    value=str(val),
                    source=src_label,
                    source_url=best_url,
                    confidence=confidence,
                    source_tier=tier,
                )

        _attr("oem_only_requirement", result.oem_only)
        _attr("approved_substitute_availability", result.substitute_available)
        _attr("obsolescence_risk", result.obsolescence_risk)
        _attr("local_presence_distributor_availability",
              "local" if tier <= SOURCE_TIER_DISTRIBUTOR else None)
