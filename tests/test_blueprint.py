from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.blueprint import Blueprint, load_blueprint
from app.config import PROJECT_ROOT

BLUEPRINT_PATH = PROJECT_ROOT / "blueprints" / "research.yaml"


def raw_blueprint() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    return data


def test_real_blueprint_loads() -> None:
    blueprint = load_blueprint(BLUEPRINT_PATH)
    assert blueprint.name == "research"
    assert blueprint.model_id("plan") == "claude-sonnet-5-5"
    assert blueprint.model_id("synthesize") == "claude-opus-5-5"
    assert blueprint.model_id("summarize") == "claude-haiku-5-5"


def test_model_override_wins() -> None:
    blueprint = load_blueprint(BLUEPRINT_PATH)
    assert blueprint.model_id("synthesize", override="claude-haiku-5-5") == "claude-haiku-5-5"


def test_cost_estimate() -> None:
    blueprint = load_blueprint(BLUEPRINT_PATH)
    # 1M input tokens at $4 + 0.5M output tokens at $20 = $14
    assert blueprint.cost_usd("claude-opus-5-5", 1_000_000, 500_000) == pytest.approx(14.0)
    assert blueprint.cost_usd("unknown-model", 1000, 1000) == 0.0


def test_unknown_key_is_rejected() -> None:
    data = raw_blueprint()
    data["limits"]["max_serches"] = 5  # typo
    with pytest.raises(ValidationError, match="max_serches"):
        Blueprint.model_validate(data)


def test_missing_step_is_rejected() -> None:
    data = raw_blueprint()
    del data["steps"]["synthesize"]
    with pytest.raises(ValidationError, match="missing steps"):
        Blueprint.model_validate(data)


def test_unknown_model_alias_is_rejected() -> None:
    data = raw_blueprint()
    data["steps"]["plan"]["model"] = "gigantic"
    with pytest.raises(ValidationError, match="unknown model alias"):
        Blueprint.model_validate(data)


def test_unpriced_model_is_rejected() -> None:
    data = raw_blueprint()
    data["models"]["fast"] = "some-new-model"
    with pytest.raises(ValidationError, match="no pricing"):
        Blueprint.model_validate(data)


def test_unknown_subtask_type_is_rejected() -> None:
    data = raw_blueprint()
    data["allowed_subtask_types"].append("send_email")
    with pytest.raises(ValidationError):
        Blueprint.model_validate(data)


def test_load_from_file(tmp_path: Path) -> None:
    path = tmp_path / "bp.yaml"
    path.write_text(yaml.safe_dump(raw_blueprint()), encoding="utf-8")
    assert load_blueprint(path).version == 1
