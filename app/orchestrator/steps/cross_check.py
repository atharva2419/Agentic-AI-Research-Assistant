"""EXECUTING / cross_check sub-tasks: find contradictions between summarized sources."""

from pydantic import BaseModel

from app.models import (
    Actor,
    Contradiction,
    ResearchSession,
    Source,
    SubTask,
    SubTaskStatus,
)
from app.orchestrator.deps import AgentDeps
from app.orchestrator.steps.common import call_llm_step, research_context, wrap_summary


class ContradictionOutput(BaseModel):
    topic: str
    claim_a: str
    source_a: str
    claim_b: str
    source_b: str
    explanation: str
    likely_cause: str


class CrossCheckOutput(BaseModel):
    contradictions: list[ContradictionOutput]


def contradiction_problems(output: CrossCheckOutput, allowed_ids: set[str]) -> list[str]:
    problems = []
    for c in output.contradictions:
        for sid in (c.source_a, c.source_b):
            if sid not in allowed_ids:
                problems.append(
                    f"contradiction '{c.topic}' cites unknown source '{sid}'; "
                    f"only these exist: {sorted(allowed_ids)}"
                )
        if c.source_a == c.source_b:
            problems.append(f"contradiction '{c.topic}' must be between two different sources")
    return problems


def sources_to_compare(session: ResearchSession, task: SubTask) -> list[Source]:
    """Kept, summarized sources found by the searches behind this task's summarize tasks."""
    assert session.plan is not None
    search_ids: set[str] = set()
    for dep in task.depends_on:
        summarize_task = session.plan.get_subtask(dep)
        if summarize_task is not None:
            search_ids.update(summarize_task.depends_on)
    summarized = {s.source_id for s in session.summaries}
    return [
        s for s in session.kept_sources() if s.id in summarized and search_ids & set(s.found_by)
    ]


async def run_cross_check(deps: AgentDeps, session: ResearchSession, task: SubTask) -> None:
    task.status = SubTaskStatus.RUNNING
    sources = sources_to_compare(session, task)
    if len(sources) < 2:
        task.status = SubTaskStatus.DONE
        task.note = "fewer than 2 summarized sources; nothing to compare"
        session.add_log(
            actor=Actor.AGENT,
            step="cross_check",
            action="skipped cross-check",
            decision=task.note,
            details={"subtask_id": task.id},
        )
        return

    summaries = {s.source_id: s for s in session.summaries}
    allowed = {s.id for s in sources}
    output = await call_llm_step(
        deps,
        session,
        "cross_check",
        CrossCheckOutput,
        values={
            "context": research_context(deps, session),
            "focus": task.focus or task.title,
            "summaries": "\n\n".join(wrap_summary(s, summaries[s.id]) for s in sources),
        },
        validate=lambda out: contradiction_problems(out, allowed),
    )

    for c in output.contradictions:
        contradiction = Contradiction(
            id=f"C{len(session.contradictions) + 1}",
            topic=c.topic,
            claim_a=c.claim_a,
            source_a=c.source_a,
            claim_b=c.claim_b,
            source_b=c.source_b,
            explanation=c.explanation,
            likely_cause=c.likely_cause,
        )
        session.contradictions.append(contradiction)
        session.add_log(
            actor=Actor.AGENT,
            step="cross_check",
            action=f"found contradiction {contradiction.id}: {c.topic}",
            decision=f"{c.source_a} vs {c.source_b}",
            reason=c.explanation,
            details=contradiction.model_dump(),
        )
    task.status = SubTaskStatus.DONE
    task.note = f"compared {len(sources)} sources, {len(output.contradictions)} contradiction(s)"
    if not output.contradictions:
        session.add_log(
            actor=Actor.AGENT,
            step="cross_check",
            action="no contradictions found",
            decision=f"compared {len(sources)} sources",
            details={"subtask_id": task.id},
        )
