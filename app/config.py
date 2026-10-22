"""Application settings, read from environment variables and the .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    anthropic_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'research.db'}"
    llm_model_override: str | None = None
    # Built-in fake AI and search: no API keys, no cost. For UI work and as a demo fallback.
    offline_mode: bool = False
    log_level: str = "INFO"
    data_dir: Path = PROJECT_ROOT / "data"  # finished sessions and reports are exported here
    blueprint_path: Path = PROJECT_ROOT / "blueprints" / "research.yaml"
    prompts_dir: Path = PROJECT_ROOT / "prompts"

    @field_validator("anthropic_api_key", "tavily_api_key", "llm_model_override", mode="before")
    @classmethod
    def empty_string_is_none(cls, value: object) -> object:
        # `KEY=` in .env arrives as "", which should mean "not set".
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
