"""Load and validate the YAML workflow blueprint (blueprints/research.yaml)."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import SubTaskType

StepName = Literal[
    "clarify", "plan", "relevance", "summarize", "cross_check", "gap_check", "synthesize"
]
REQUIRED_STEPS: tuple[StepName, ...] = (
    "clarify",
    "plan",
    "relevance",
    "summarize",
    "cross_check",
    "gap_check",
    "synthesize",
)
Effort = Literal["low", "medium", "high"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StepConfig(StrictModel):
    prompt: str = Field(pattern=r"^[a-z_]+\.md$")
    model: str  # an alias from Blueprint.models
    effort: Effort = "medium"
    max_tokens: int = Field(gt=0, le=128_000)


class Price(StrictModel):
    input: float = Field(ge=0)  # USD per million tokens
    output: float = Field(ge=0)


class SearchConfig(StrictModel):
    provider: Literal["tavily"]
    max_results: int = Field(ge=1, le=20)
    depth: Literal["basic", "advanced"] = "basic"


class Limits(StrictModel):
    max_subtasks: int = Field(ge=1)
    max_searches: int = Field(ge=1)
    max_replans: int = Field(ge=0)
    max_clarifying_questions: int = Field(ge=0)
    max_gap_questions: int = Field(ge=0)
    max_sources_summarized: int = Field(ge=1)
    max_cost_usd: float = Field(gt=0)
    llm_max_retries: int = Field(ge=0, le=5)
    search_timeout_s: float = Field(gt=0)
    llm_timeout_s: float = Field(gt=0)
    parallel_searches: int = Field(ge=1)
    parallel_llm_calls: int = Field(ge=1)


class FilteringConfig(StrictModel):
    default_recency_days: int = Field(ge=1, le=3650)
    relevance_threshold: float = Field(ge=0, le=1)
    unknown_date_policy: Literal["keep_flagged", "exclude"]
    min_content_chars: int = Field(ge=0)
    max_sources_per_domain: int = Field(ge=1)
    relevance_content_chars: int = Field(gt=0)
    summarize_content_chars: int = Field(gt=0)


class Blueprint(StrictModel):
    name: str
    version: int
    description: str
    models: dict[str, str]
    pricing: dict[str, Price]
    steps: dict[StepName, StepConfig]
    allowed_subtask_types: list[SubTaskType]
    search: SearchConfig
    limits: Limits
    filtering: FilteringConfig

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        missing = [s for s in REQUIRED_STEPS if s not in self.steps]
        if missing:
            raise ValueError(f"blueprint is missing steps: {missing}")
        for name, step in self.steps.items():
            if step.model not in self.models:
                raise ValueError(f"step '{name}' uses unknown model alias '{step.model}'")
        unpriced = sorted(set(self.models.values()) - set(self.pricing))
        if unpriced:
            raise ValueError(f"no pricing for models: {unpriced}")
        if SubTaskType.SEARCH not in self.allowed_subtask_types:
            raise ValueError("allowed_subtask_types must include 'search'")
        return self

    def model_id(self, step: StepName, override: str | None = None) -> str:
        """The concrete model ID for a step. `override` (from settings) wins, for cheap runs."""
        return override or self.models[self.steps[step].model]

    def cost_usd(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        price = self.pricing.get(model_id)
        if price is None:
            return 0.0
        return (input_tokens * price.input + output_tokens * price.output) / 1_000_000


def load_blueprint(path: Path) -> Blueprint:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Blueprint.model_validate(data)
