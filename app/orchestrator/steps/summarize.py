"""EXECUTING / summarize sub-tasks: one cheap LLM call per kept source, run in parallel."""

import asyncio

from pydantic import BaseModel

from app.llm.base import LLMError, StructuredOutputError
from app.models import Actor, Quote, ResearchSession, Source, SourceSummary, SubTask, SubTaskStatus
from app.orchestrator.citations import verify_quotes
from app.orchestrator.deps import AgentDeps
from app.orchestrator.steps.common import (
    call_llm_step,
    research_context,
    research_questions_text,
    wrap_source,
)


class QuoteOutput(BaseModel):
    text: str
    context: str


class SummaryOutput(BaseModel):
    summary: str
    key_takeaways: list[str]
    claims: list[str]
    quotes: list[QuoteOutput]


def sources_to_summarize(
    session: ResearchSession, task: SubTask, max_total: int
) -> tuple[list[Source], int]:
    """Kept, not-yet-summarized sources found by this task's searches, within the summary budget.
    Returns (sources, number skipped because of the budget)."""
    search_ids = set(task.depends_on)
    done = {s.source_id for s in session.summaries}
    candidates = [
        s for s in session.kept_sources() if search_ids & set(s.found_by) and s.id not in done
    ]
    room = max(0, max_total - len(session.summaries))
    return candidates[:room], max(0, len(candidates) - room)


async def run_summarize(deps: AgentDeps, session: ResearchSession, task: SubTask) -> None:
    task.status = SubTaskStatus.RUNNING
    limits = deps.blueprint.limits
    sources, over_budget = sources_to_summarize(session, task, limits.max_sources_summarized)
    semaphore = asyncio.Semaphore(limits.parallel_llm_calls)
    content_limit = deps.blueprint.filtering.summarize_content_chars

    async def summarize_one(source: Source) -> SummaryOutput | None:
        async with semaphore:
            try:
                return await call_llm_step(
                    deps,
                    session,
                    "summarize",
                    SummaryOutput,
                    values={
                        "context": research_context(deps, session),
                        "research_questions": research_questions_text(session),
                        "source": wrap_source(source, source.content[:content_limit]),
                    },
                )
            except (StructuredOutputError, LLMError) as exc:
                session.add_log(
                    actor=Actor.SYSTEM,
                    step="summarize",
                    action=f"could not summarize {source.id}",
                    decision="source kept without a summary (it will not be cited)",
                    reason=str(exc),
                    details={"source_id": source.id},
                )
                return None

    outputs = await asyncio.gather(*(summarize_one(s) for s in sources))

    summarized = 0
    for source, output in zip(sources, outputs, strict=True):
        if output is None:
            continue
        quotes = [Quote(text=q.text, context=q.context) for q in output.quotes]
        found, missing = verify_quotes(quotes, source.content)
        session.summaries.append(
            SourceSummary(
                source_id=source.id,
                summary=output.summary,
                key_takeaways=output.key_takeaways,
                claims=output.claims,
                quotes=found,
            )
        )
        summarized += 1
        session.add_log(
            actor=Actor.AGENT,
            step="summarize",
            action=f"summarized {source.id} ({source.domain})",
            decision=f"{len(output.key_takeaways)} takeaways, {len(found)} verified quotes",
            reason=output.summary[:200],
            details={"source_id": source.id},
        )
        if missing:
            session.add_log(
                actor=Actor.SYSTEM,
                step="summarize",
                action=f"removed {len(missing)} unverified quote(s) from {source.id}",
                decision="quotes not found word for word in the source text",
                reason="guards against made-up quotes",
                details={"source_id": source.id, "removed": [q.text for q in missing]},
            )

    if over_budget:
        session.add_log(
            actor=Actor.SYSTEM,
            step="summarize",
            action=f"skipped {over_budget} source(s)",
            decision="summary budget reached",
            reason=f"limit is {limits.max_sources_summarized} summaries per session",
            details={"subtask_id": task.id},
        )
    task.status = SubTaskStatus.DONE
    task.note = f"summarized {summarized} source(s)"
