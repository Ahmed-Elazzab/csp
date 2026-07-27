"""Application configuration – loaded once via lru_cache."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ───────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://csp_user:csp_pass@localhost:5432/csp_db"

    # ── LLM Configuration ──────────────────────────────────────────────────────
    # Provider: openai | azure_openai | anthropic | gemini | ollama | openai_compatible
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4.1"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_VERSION: str = ""          # Azure OpenAI only
    LLM_ORGANIZATION: str = ""
    LLM_PROJECT: str = ""
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 3

    # ── Legacy OpenAI fields (deprecated – use LLM_* instead) ─────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    @property
    def effective_llm_api_key(self) -> str:
        """Return LLM_API_KEY, falling back to legacy OPENAI_API_KEY."""
        return self.LLM_API_KEY or self.OPENAI_API_KEY

    @property
    def llm_configured(self) -> bool:
        return bool(self.effective_llm_api_key)

    # ── Search Configuration ───────────────────────────────────────────────────
    SEARCH_PROVIDER: str = "duckduckgo"  # duckduckgo | tavily | serpapi
    SEARCH_MAX_RESULTS: int = 10
    SEARCH_TIMEOUT: int = 30
    TAVILY_API_KEY: str = ""
    SERPAPI_KEY: str = ""

    # Legacy
    CONFIDENCE_THRESHOLD: float = 0.70

    # ── Embeddings (Future RAG) ────────────────────────────────────────────────
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_API_KEY: str = ""

    # ── Vector Database (Future) ───────────────────────────────────────────────
    VECTOR_DB_PROVIDER: str = ""
    VECTOR_DB_URL: str = ""
    VECTOR_DB_API_KEY: str = ""
    VECTOR_DB_COLLECTION: str = ""

    # ── Observability ──────────────────────────────────────────────────────────
    ENABLE_TRACING: bool = False
    LOG_LLM_REQUESTS: bool = False
    LOG_LLM_RESPONSES: bool = False

    # ── Excel (historical compatibility) ──────────────────────────────────────
    EXCEL_PATH: str = "data/Critical Parts Attributes.xlsx"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

