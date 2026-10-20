"""A scripted LLM for tests: no network, no cost, fully deterministic.

Give it a queue of responses per step. Each response is either a Pydantic object (sent as JSON),
a raw string (to test invalid output), or a function of the request (to answer based on input).
"""

from collections.abc import Callable

from pydantic import BaseModel

from app.llm.base import LLMRequest, LLMResponse

type ScriptedResponse = BaseModel | str | Callable[[LLMRequest], BaseModel | str]


class FakeLLM:
    def __init__(self, script: dict[str, list[ScriptedResponse]] | None = None) -> None:
        self._script: dict[str, list[ScriptedResponse]] = {
            step: list(responses) for step, responses in (script or {}).items()
        }
        self.calls: list[LLMRequest] = []

    def add(self, step: str, *responses: ScriptedResponse) -> None:
        self._script.setdefault(step, []).extend(responses)

    def set(self, step: str, *responses: ScriptedResponse) -> None:
        """Replace the queued responses for a step."""
        self._script[step] = list(responses)

    def calls_for(self, step: str) -> list[LLMRequest]:
        return [c for c in self.calls if c.step == step]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        queue = self._script.get(request.step)
        if not queue:
            raise AssertionError(f"FakeLLM has no scripted response left for step '{request.step}'")
        item = queue.pop(0)
        if callable(item) and not isinstance(item, BaseModel):
            item = item(request)
        text = item.model_dump_json() if isinstance(item, BaseModel) else item
        return LLMResponse(
            text=text,
            model=request.model,
            input_tokens=sum(len(m.content) for m in request.messages) // 4,
            output_tokens=len(text) // 4,
            stop_reason="end_turn",
        )
