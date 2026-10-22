"""Helpers shared by all steps: the LLM call wrapper, prompt context, untrusted-content wrapping."""

import re
from collections.abc import Callable
from datetime import timedelta

from pydantic import BaseModel

from app.blueprint import StepName
from app.llm.base import LLMMessage, LLMRequest, LLMResponse, StructuredOutputError, structured_call
from app.models import Actor, ResearchSession, Source, SourceSummary
from app.orchestrator.deps import AgentDeps


async def call_llm_step[T: BaseModel](
    deps: AgentDeps,
    session: ResearchSession,
    step: StepName,
    output_model: type[T],
    values: dict[str, str],
    validate: Callable[[T], list[str]] | None = None,
) -> T:
    """Render the step's prompt, call the LLM with validation + retries, and record the cost."""
    config = deps.blueprint.steps[step]
    prompt = deps.prompts.get(config.prompt).render(**values)
    request = LLMRequest(
        step=step,
        model=deps.blueprint.model_id(step, deps.model_override),
        system=prompt.system,
        messages=[LLMMessage(role="user", content=prompt.user)],
        max_tokens=config.max_tokens,
        effort=config.effort,
    )
    try:
        result = await structured_call(
            deps.llm,
            request,
            output_model,
            validate=validate,
            max_retries=deps.blueprint.limits.llm_max_retries,
        )
    except StructuredOutputError as exc:
        record_usage(deps, session, exc.responses)
        session.add_log(
            actor=Actor.SYSTEM,
            step=step,
            action="LLM output rejected",
            decision=f"gave up after {exc.attempts} attempts",
            reason="; ".join(exc.errors[:5]),
        )
        raise
    record_usage(deps, session, result.responses)
    if result.attempts > 1:
        session.add_log(
            actor=Actor.SYSTEM,
            step=step,
            action="LLM output corrected",
            decision=f"valid after {result.attempts} attempts",
            reason="the first answer failed validation and was sent back with the errors",
        )
    return result.value


def record_usage(deps: AgentDeps, session: ResearchSession, responses: list[LLMResponse]) -> None:
    budget = session.budget
    for response in responses:
        budget.llm_calls += 1
        budget.input_tokens += response.input_tokens
        budget.output_tokens += response.output_tokens
        budget.cost_usd += deps.blueprint.cost_usd(
            response.model, response.input_tokens, response.output_tokens
        )


def research_context(deps: AgentDeps, session: ResearchSession) -> str:
    """The shared context block every prompt receives. This is how the agent adapts: user
    answers, assumptions, the recency window and past research all flow into every step."""
    today = deps.today()
    cutoff = today - timedelta(days=session.settings.recency_days)
    lines = [
        f"Topic: {session.topic}",
        f"Today's date: {today.isoformat()}",
        f"Recency window: sources published on or after {cutoff.isoformat()} "
        f"({session.settings.recency_days} days)",
    ]
    if session.settings.keywords:
        lines.append(
            "Priority keywords from the user: "
            + ", ".join(session.settings.keywords)
            + ". Favour angles and sources that cover them; never exclude a source only because "
            "it doesn't mention them."
        )
    answered = [q for q in session.questions if q.answer is not None]
    if answered:
        lines.append("User clarifications:")
        lines += [f"- Q: {q.question} A: {q.answer}" for q in answered]
    if session.assumptions:
        lines.append("Assumptions (the user skipped these questions; state them, don't hide them):")
        lines += [f"- {a}" for a in session.assumptions]
    if session.related_memory:
        lines.append(
            "From past research by this user (context only: not evidence for this session, "
            "which must come from newly collected sources):"
        )
        for match in session.related_memory:
            age = max(0, (today - match.created_at.date()).days)
            findings = "; ".join(match.key_findings[:3])
            lines.append(f"- {match.topic} (researched {age} days ago): {findings}")
    return "\n".join(lines)


def research_questions_text(session: ResearchSession) -> str:
    if session.plan is None:
        return "(none yet)"
    return "\n".join(f"{q.id}: {q.text}" for q in session.plan.research_questions)


_SOURCE_TAG = re.compile(r"</?\s*source", re.IGNORECASE)


def escape_untrusted(text: str) -> str:
    """Neutralize anything in web content that could close or fake our <source> delimiters."""
    return _SOURCE_TAG.sub(lambda m: m.group(0).replace("<", "&lt;"), text)


def _attr(value: str) -> str:
    return escape_untrusted(value).replace('"', "'").replace("\n", " ")


def wrap_source(source: Source, body: str) -> str:
    """Wrap untrusted web text in clearly delimited tags. Prompts say: data, never instructions."""
    published = source.published_date.isoformat() if source.published_date else "unknown"
    return (
        f'<source id="{source.id}" title="{_attr(source.title)}" domain="{source.domain}" '
        f'published="{published}">\n{escape_untrusted(body)}\n</source>'
    )


def wrap_summary(source: Source, summary: SourceSummary) -> str:
    """A summary still derives from untrusted content, so it is wrapped the same way."""
    body = "\n".join(
        [
            f"Summary: {summary.summary}",
            "Key takeaways:",
            *[f"- {t}" for t in summary.key_takeaways],
            "Claims:",
            *[f"- {c}" for c in summary.claims],
        ]
    )
    return wrap_source(source, body)
