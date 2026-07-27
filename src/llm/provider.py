"""
LLM Provider abstraction layer.

Switching providers requires only a change in environment variables.
No application code changes are needed.

Supported providers:
  openai             – OpenAI API
  azure_openai       – Azure OpenAI Service
  anthropic          – Anthropic Claude
  gemini             – Google Gemini
  ollama             – Local Ollama server (OpenAI-compatible)
  openai_compatible  – Any OpenAI-compatible endpoint (vLLM, LM Studio, etc.)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


# ── Shared data types ──────────────────────────────────────────────────────────

@dataclass
class LLMMessage:
    role: str    # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)
    raw: Any = None

    def parse_json(self) -> dict:
        """Parse response content as JSON, with basic cleanup."""
        text = self.content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                l for l in lines
                if not l.startswith("```")
            ).strip()
        return json.loads(text)


# ── Abstract base ──────────────────────────────────────────────────────────────

class BaseLLMProvider(ABC):
    """Contract that every LLM provider adapter must fulfil."""

    @abstractmethod
    def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Send a list of messages and return a completion."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier."""
        ...


# ── OpenAI-compatible provider (covers OpenAI, Azure, Ollama, vLLM, LM Studio) ─

class OpenAICompatibleProvider(BaseLLMProvider):
    """
    Handles any endpoint that speaks the OpenAI Chat Completions API.

    Covers: openai | azure_openai | ollama | vllm | lmstudio | openai_compatible
    """

    def __init__(self, settings: "Settings") -> None:
        self._s = settings
        self._client = None

    def _build_client(self):
        from openai import OpenAI, AzureOpenAI  # type: ignore

        api_key = self._s.effective_llm_api_key or "not-required"

        if self._s.LLM_PROVIDER == "azure_openai":
            return AzureOpenAI(
                api_key=api_key,
                azure_endpoint=self._s.LLM_BASE_URL,
                api_version=self._s.LLM_API_VERSION or "2024-02-01",
                organization=self._s.LLM_ORGANIZATION or None,
                timeout=self._s.LLM_TIMEOUT,
                max_retries=self._s.LLM_MAX_RETRIES,
            )

        return OpenAI(
            api_key=api_key,
            base_url=self._s.LLM_BASE_URL or None,
            organization=self._s.LLM_ORGANIZATION or None,
            project=self._s.LLM_PROJECT or None,
            timeout=self._s.LLM_TIMEOUT,
            max_retries=self._s.LLM_MAX_RETRIES,
        )

    @property
    def _client_instance(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        if self._s.LOG_LLM_REQUESTS:
            logger.debug("LLM request (%s): %d messages", self._s.LLM_MODEL, len(messages))

        response = self._client_instance.chat.completions.create(
            model=self._s.LLM_MODEL,
            messages=[m.to_dict() for m in messages],
            temperature=kwargs.get("temperature", self._s.LLM_TEMPERATURE),
            max_tokens=kwargs.get("max_tokens", self._s.LLM_MAX_TOKENS),
            response_format=kwargs.get("response_format", {"type": "json_object"}),
        )
        content = response.choices[0].message.content or ""

        if self._s.LOG_LLM_RESPONSES:
            logger.debug("LLM response: %s…", content[:200])

        return LLMResponse(
            content=content,
            model=response.model,
            provider=self.provider_name,
            usage={
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
            },
            raw=response,
        )

    @property
    def provider_name(self) -> str:
        return self._s.LLM_PROVIDER


# ── Anthropic provider ─────────────────────────────────────────────────────────

class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude via the anthropic SDK."""

    def __init__(self, settings: "Settings") -> None:
        self._s = settings
        self._client = None

    @property
    def _client_instance(self):
        if self._client is None:
            try:
                import anthropic  # type: ignore
            except ImportError:
                raise ImportError("Run: pip install anthropic")
            self._client = anthropic.Anthropic(
                api_key=self._s.effective_llm_api_key,
                timeout=self._s.LLM_TIMEOUT,
                max_retries=self._s.LLM_MAX_RETRIES,
            )
        return self._client

    def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        system_content = ""
        user_messages = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            else:
                user_messages.append(m.to_dict())

        response = self._client_instance.messages.create(
            model=self._s.LLM_MODEL,
            max_tokens=kwargs.get("max_tokens", self._s.LLM_MAX_TOKENS),
            system=system_content or "Return only valid JSON.",
            messages=user_messages,
            temperature=kwargs.get("temperature", self._s.LLM_TEMPERATURE),
        )
        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            model=response.model,
            provider="anthropic",
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            raw=response,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"


# ── Google Gemini provider ─────────────────────────────────────────────────────

class GeminiProvider(BaseLLMProvider):
    """Google Gemini via the google-generativeai SDK."""

    def __init__(self, settings: "Settings") -> None:
        self._s = settings
        self._model = None

    @property
    def _model_instance(self):
        if self._model is None:
            try:
                import google.generativeai as genai  # type: ignore
            except ImportError:
                raise ImportError("Run: pip install google-generativeai")
            genai.configure(api_key=self._s.effective_llm_api_key)
            self._model = genai.GenerativeModel(
                model_name=self._s.LLM_MODEL,
                generation_config={
                    "temperature": self._s.LLM_TEMPERATURE,
                    "max_output_tokens": self._s.LLM_MAX_TOKENS,
                    "response_mime_type": "application/json",
                },
            )
        return self._model

    def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        prompt = "\n\n".join(f"[{m.role.upper()}]\n{m.content}" for m in messages)
        response = self._model_instance.generate_content(prompt)
        return LLMResponse(
            content=response.text,
            model=self._s.LLM_MODEL,
            provider="gemini",
            usage={},
            raw=response,
        )

    @property
    def provider_name(self) -> str:
        return "gemini"


# ── Factory ────────────────────────────────────────────────────────────────────

_OPENAI_COMPAT = frozenset({
    "openai", "azure_openai", "ollama", "vllm",
    "lmstudio", "openai_compatible", "openai-compatible",
})


def get_llm_provider(settings: "Settings") -> BaseLLMProvider:
    """
    Return the correct provider adapter based on LLM_PROVIDER in settings.

    Raises ValueError for completely unknown providers.
    """
    provider = (settings.LLM_PROVIDER or "openai").lower().strip()

    if provider in _OPENAI_COMPAT:
        return OpenAICompatibleProvider(settings)
    if provider == "anthropic":
        return AnthropicProvider(settings)
    if provider in ("gemini", "google", "google_gemini"):
        return GeminiProvider(settings)

    logger.warning(
        "Unknown LLM_PROVIDER '%s' – falling back to OpenAI-compatible. "
        "Supported: %s",
        provider,
        ", ".join(sorted(_OPENAI_COMPAT | {"anthropic", "gemini"})),
    )
    return OpenAICompatibleProvider(settings)
