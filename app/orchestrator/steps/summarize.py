"""EXECUTING / summarize sub-tasks: one cheap LLM call per kept source, run in parallel."""

import asyncio

from pydantic import BaseModel

from app.llm.base import LLMError, StructuredOutputError
from app.models import (
    Actor,
    Quote,
    ResearchSession,
    Source,
    SourceSummary,
    SubTask,
    SubTaskStatus,
    SubTaskType,
)
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


def fair_quota(session: ResearchSession, task: SubTask, remaining: int) -> int:
    """This task's share of the remaining summary budget.

    The budget is split across this task and the summarize tasks still waiting to run, in
    proportion to how many searches each one covers. It is recomputed when each task runs, so
    slots a task doesn't use roll over to the tasks after it. The last task gets all that's left.
    """
    assert session.plan is not None
    waiting = [
        t
        for t in session.plan.subtasks
        if t.type == SubTaskType.SUMMARIZE and t.status == SubTaskStatus.PENDING and t.id != task.id
    ]
    if not waiting:
        return remaining
    mine = len(task.depends_on)
    total = mine + sum(len(t.depends_on) for t in waiting)
    return min(remaining, max(1, remaining * mine // total))


def _by_relevance(source: Source) -> float:
    # Sources the relevance judge couldn't score (call failed) go after scored ones.
    return source.relevance_score if source.relevance_score is not None else -1.0


def sources_to_summarize(
    session: ResearchSession, task: SubTask, max_total: int
) -> tuple[list[Source], list[Source]]:
    """Pick which sources this task summarizes. Returns (chosen, skipped for budget).

    Candidates are kept, not-yet-summarized sources found by this task's searches. Selection
    takes turns across the searches, each time picking that search's most relevant remaining
    source, so every search (and so every research question) gets its best sources first.
    """
    done = {s.source_id for s in session.summaries}
    kept = [s for s in session.kept_sources() if s.id not in done]
    per_search = [
        sorted((s for s in kept if search_id in s.found_by), key=_by_relevance, reverse=True)
        for search_id in task.depends_on
    ]
    candidates = {s.id: s for queue in per_search for s in queue}

    remaining = max(0, max_total - len(session.summaries))
    quota = fair_quota(session, task, remaining)
    chosen: list[Source] = []
    picked: set[str] = set()
    while len(chosen) < quota and any(per_search):
        # One round: each search offers its best unpicked source; take the offers best-first,
        # so if the quota runs out mid-round, the weaker offers are the ones left out.
        offers = []
        for queue in per_search:
            while queue and queue[0].id in picked:  # found by an earlier search too
                queue.pop(0)
            if queue:
                offers.append(queue.pop(0))
        for source in sorted(offers, key=_by_relevance, reverse=True):
            if len(chosen) < quota and source.id not in picked:
                chosen.append(source)
                picked.add(source.id)

    skipped = [s for sid, s in candidates.items() if sid not in picked]
    return chosen, skipped


async def run_summarize(deps: AgentDeps, session: ResearchSession, task: SubTask) -> None:
    task.status = SubTaskStatus.RUNNING
    limits = deps.blueprint.limits
    sources, skipped = sources_to_summarize(session, task, limits.max_sources_summarized)
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

    if skipped:
        listed = ", ".join(f"{s.id} ({_by_relevance(s):.2f})" for s in skipped)
        session.add_log(
            actor=Actor.SYSTEM,
            step="summarize",
            action=f"skipped {len(skipped)} source(s): {listed}",
            decision=f"this task's share of the summary budget was {len(sources)}",
            reason=(
                f"limit is {limits.max_sources_summarized} summaries per session, shared fairly "
                "across summarize tasks; the most relevant source of each search is picked first"
            ),
            details={"subtask_id": task.id, "skipped": [s.id for s in skipped]},
        )
    task.status = SubTaskStatus.DONE
    task.note = f"summarized {summarized} source(s)"
