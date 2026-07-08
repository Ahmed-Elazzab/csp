"""Application configuration – loaded once via lru_cache."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql://csp_user:csp_pass@localhost:5432/csp_db"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # Research
    SEARCH_MAX_RESULTS: int = 5
    CONFIDENCE_THRESHOLD: float = 0.70

    # Excel
    EXCEL_PATH: str = "data/Critical Parts Attributes.xlsx"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
