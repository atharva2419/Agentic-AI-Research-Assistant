"""The LLM interface and the one helper every step uses to get validated, structured output.

Any provider (Anthropic, a fake for tests, ...) implements `LLMClient.complete()`, which returns
raw text. `structured_call()` turns that text into a validated Pydantic object, retrying with the
error messages when the output is invalid.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMRequest:
    step: str  # which pipeline step is calling, e.g. "plan" (used by logs and the fake)
    model: str
    system: str
    messages: list[LLMMessage]
    max_tokens: int
    effort: Literal["low", "medium", "high"] = "medium"
    output_schema: type[BaseModel] | None = None  # constrain the output to this JSON schema


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None


class LLMClient(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    """The provider call itself failed (network, refusal, rate limit after retries, ...)."""


class StructuredOutputError(Exception):
    """The model kept returning output that failed validation.

    `last_valid_shape` is the last answer that matched the schema but failed the semantic checks
    (None if no answer even matched the schema). Callers may use it to degrade gracefully, e.g.
    keep a report but flag its unsupported statements.
    """

    def __init__(
        self,
        step: str,
        attempts: int,
        errors: list[str],
        last_valid_shape: BaseModel | None = None,
        responses: list["LLMResponse"] | None = None,
    ) -> None:
        self.step = step
        self.attempts = attempts
        self.errors = errors
        self.last_valid_shape = last_valid_shape
        self.responses = responses or []
        super().__init__(f"step '{step}' failed validation after {attempts} attempts: {errors}")


@dataclass
class StructuredResult[T: BaseModel]:
    value: T
    attempts: int
    responses: list[LLMResponse] = field(default_factory=list)  # one per attempt, for usage


def _schema_errors(error: ValidationError) -> list[str]:
    errors = []
    for e in error.errors():
        location = ".".join(str(part) for part in e["loc"]) or "(root)"
        errors.append(f"{location}: {e['msg']}")
    return errors


async def structured_call[T: BaseModel](
    llm: LLMClient,
    request: LLMRequest,
    output_model: type[T],
    validate: Callable[[T], list[str]] | None = None,
    max_retries: int = 2,
) -> StructuredResult[T]:
    """Call the LLM and return a validated `output_model`.

    Two layers of checks:
    1. schema: the text must parse as JSON matching `output_model` (Pydantic);
    2. semantic: `validate(value)` returns problems code can see but a schema can't
       (e.g. a cited source ID that doesn't exist, or a cycle in the plan).

    On failure the bad answer and the list of problems are sent back to the model, up to
    `max_retries` times. Then `StructuredOutputError` is raised for the caller to handle.
    """
    messages = list(request.messages)
    responses: list[LLMResponse] = []
    errors: list[str] = []
    last_valid_shape: T | None = None

    for attempt in range(1, max_retries + 2):
        current = LLMRequest(
            step=request.step,
            model=request.model,
            system=request.system,
            messages=messages,
            max_tokens=request.max_tokens,
            effort=request.effort,
            output_schema=output_model,
        )
        response = await llm.complete(current)
        responses.append(response)

        try:
            value = output_model.model_validate_json(response.text)
        except ValidationError as exc:
            errors = _schema_errors(exc)
        else:
            errors = validate(value) if validate else []
            if not errors:
                return StructuredResult(value=value, attempts=attempt, responses=responses)
            last_valid_shape = value

        messages = [
            *messages,
            LLMMessage(role="assistant", content=response.text),
            LLMMessage(
                role="user",
                content=(
                    "Your previous answer had these problems:\n"
                    + "\n".join(f"- {e}" for e in errors)
                    + "\nReturn a corrected answer as JSON that fixes all of them."
                ),
            ),
        ]

    raise StructuredOutputError(
        step=request.step,
        attempts=len(responses),
        errors=errors,
        last_valid_shape=last_valid_shape,
        responses=responses,
    )
