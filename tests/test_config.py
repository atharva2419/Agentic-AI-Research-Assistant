import pytest

from app.config import Settings


def test_empty_values_mean_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_MODEL_OVERRIDE", "  ")
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key is None
    assert settings.llm_model_override is None


def test_keys_are_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    settings = Settings(_env_file=None)
    assert settings.tavily_api_key is not None
    assert settings.tavily_api_key.get_secret_value() == "tvly-secret"
    assert "tvly-secret" not in repr(settings)
