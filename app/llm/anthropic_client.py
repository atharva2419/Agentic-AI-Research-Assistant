"""LLMClient implementation for Claude, using the official `anthropic` SDK."""

from typing import Any

import anthropic

from app.llm.base import LLMError, LLMRequest, LLMResponse

# Models that support server-side refusal fallbacks: if a safety classifier declines a request
# (possible with web content on sensitive topics), the API retries on a suitable model instead
# of failing the step.
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLMClient:
    def __init__(self, api_key: str, timeout_s: float = 120.0, max_retries: int = 2) -> None:
        # The SDK itself retries rate limits, overload and connection errors with backoff.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        output_config: dict[str, Any] = {"effort": request.effort}
        if request.output_schema is not None:
            # Structured outputs: the response is constrained to this JSON schema.
            output_config["format"] = {
                "type": "json_schema",
                "schema": anthropic.transform_schema(request.output_schema),
            }
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "output_config": output_config,
        }
        if request.model in FALLBACK_MODELS:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"

        try:
            # Streaming avoids HTTP timeouts on long outputs (e.g. the final report).
            async with self._client.beta.messages.stream(**kwargs) as stream:
                message = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise LLMError(f"{request.step}: API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"{request.step}: could not reach the API: {exc}") from exc

        if message.stop_reason == "refusal":
            raise LLMError(f"{request.step}: the model declined this request")
        if message.stop_reason == "max_tokens":
            raise LLMError(
                f"{request.step}: output hit max_tokens ({request.max_tokens}); "
                "raise it in the blueprint"
            )
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason,
        )
