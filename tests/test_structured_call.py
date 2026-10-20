import pytest
from pydantic import BaseModel, Field

from app.llm.base import LLMMessage, LLMRequest, StructuredOutputError, structured_call
from app.llm.fake import FakeLLM


class Verdict(BaseModel):
    score: float = Field(ge=0, le=1)
    reason: str


def make_request() -> LLMRequest:
    return LLMRequest(
        step="relevance",
        model="test-model",
        system="Judge relevance.",
        messages=[LLMMessage(role="user", content="Is this relevant?")],
        max_tokens=100,
    )


async def test_valid_output_on_first_try() -> None:
    llm = FakeLLM({"relevance": [Verdict(score=0.9, reason="on topic")]})
    result = await structured_call(llm, make_request(), Verdict)
    assert result.value.score == 0.9
    assert result.attempts == 1
    assert llm.calls[0].output_schema is Verdict


async def test_invalid_json_is_retried_with_the_error() -> None:
    llm = FakeLLM({"relevance": ["not json", Verdict(score=0.4, reason="partly")]})
    result = await structured_call(llm, make_request(), Verdict)
    assert result.value.score == 0.4
    assert result.attempts == 2
    retry_messages = llm.calls[1].messages
    assert retry_messages[1] == LLMMessage(role="assistant", content="not json")
    assert "problems" in retry_messages[2].content


async def test_schema_violation_is_retried() -> None:
    llm = FakeLLM({"relevance": ['{"score": 7, "reason": "x"}', Verdict(score=0.7, reason="ok")]})
    result = await structured_call(llm, make_request(), Verdict)
    assert result.attempts == 2
    assert "score" in llm.calls[1].messages[-1].content


async def test_semantic_validator_triggers_retry() -> None:
    def must_explain(v: Verdict) -> list[str]:
        return [] if len(v.reason) > 3 else ["reason is too short"]

    llm = FakeLLM(
        {"relevance": [Verdict(score=0.5, reason="x"), Verdict(score=0.5, reason="clear")]}
    )
    result = await structured_call(llm, make_request(), Verdict, validate=must_explain)
    assert result.value.reason == "clear"
    assert "reason is too short" in llm.calls[1].messages[-1].content


async def test_gives_up_after_max_retries() -> None:
    llm = FakeLLM({"relevance": ["bad", "bad", "bad"]})
    with pytest.raises(StructuredOutputError) as exc_info:
        await structured_call(llm, make_request(), Verdict, max_retries=2)
    assert exc_info.value.attempts == 3
    assert exc_info.value.step == "relevance"
    assert len(llm.calls) == 3


async def test_usage_from_every_attempt_is_kept() -> None:
    llm = FakeLLM({"relevance": ["bad", Verdict(score=0.2, reason="off topic")]})
    result = await structured_call(llm, make_request(), Verdict)
    assert len(result.responses) == 2


async def test_fake_llm_fails_loudly_when_script_runs_out() -> None:
    llm = FakeLLM()
    with pytest.raises(AssertionError, match="no scripted response"):
        await structured_call(llm, make_request(), Verdict)
