"""EXECUTING / search sub-tasks: search the web, apply code rules, then the LLM relevance judge.

Pattern used here and in the other execution steps: do the slow I/O (web searches, LLM calls)
in parallel, then apply the results to the session one at a time, in plan order. Source IDs
and the action log therefore come out in the same order every run.
"""

import asyncio

from pydantic import BaseModel, Field

from app.filtering import apply_rules, domain_of, normalize_url
from app.llm.base import LLMError, StructuredOutputError
from app.models import (
    Actor,
    Exclusion,
    ExclusionStage,
    ResearchSession,
    Source,
    SourceStatus,
    SubTask,
    SubTaskStatus,
)
from app.orchestrator.deps import AgentDeps
from app.orchestrator.steps.common import (
    call_llm_step,
    research_context,
    research_questions_text,
    wrap_source,
)
from app.search.base import SearchError, SearchQuery, SearchResult

# --- LLM output schema for the relevance judge ---


class RelevanceJudgment(BaseModel):
    source_id: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class RelevanceOutput(BaseModel):
    judgments: list[RelevanceJudgment]


def judgment_problems(output: RelevanceOutput, expected_ids: set[str]) -> list[str]:
    seen = [j.source_id for j in output.judgments]
    problems = []
    missing = expected_ids - set(seen)
    unknown = set(seen) - expected_ids
    duplicated = {sid for sid in seen if seen.count(sid) > 1}
    if missing:
        problems.append(f"no judgment for sources {sorted(missing)}; judge every source")
    if unknown:
        problems.append(f"judged unknown sources {sorted(unknown)}; judge only the given sources")
    if duplicated:
        problems.append(f"sources judged more than once: {sorted(duplicated)}")
    return problems


async def run_searches(deps: AgentDeps, session: ResearchSession, tasks: list[SubTask]) -> None:
    """Run a batch of ready search sub-tasks."""
    limits = deps.blueprint.limits
    semaphore = asyncio.Semaphore(limits.parallel_searches)

    async def search_one(task: SubTask) -> list[SearchResult]:
        async with semaphore:
            query = SearchQuery(
                query=task.query or task.title,
                mode=task.search_mode,
                max_results=deps.blueprint.search.max_results,
            )
            return await asyncio.wait_for(
                deps.search.search(query), timeout=limits.search_timeout_s
            )

    for task in tasks:
        task.status = SubTaskStatus.RUNNING
    outcomes = await asyncio.gather(*(search_one(t) for t in tasks), return_exceptions=True)

    candidates: dict[str, list[Source]] = {}
    for task, outcome in zip(tasks, outcomes, strict=True):
        session.budget.searches += 1
        if isinstance(outcome, SearchError | TimeoutError):
            task.status = SubTaskStatus.FAILED
            task.note = f"search failed: {outcome}"
            session.add_log(
                actor=Actor.AGENT,
                step="search",
                action=f"search failed: '{task.query}'",
                decision="sub-task marked failed; dependents continue with other sources",
                reason=str(outcome) or type(outcome).__name__,
                details={"subtask_id": task.id},
            )
            continue
        if isinstance(outcome, BaseException):
            raise outcome
        candidates[task.id] = _apply_search_results(deps, session, task, outcome)

    to_judge = [(t, candidates[t.id]) for t in tasks if candidates.get(t.id)]
    judgments = await asyncio.gather(
        *(_judge_relevance(deps, session, task, sources) for task, sources in to_judge)
    )
    for (_task, sources), result in zip(to_judge, judgments, strict=True):
        _apply_judgments(session, sources, result)

    for task in tasks:
        if task.status == SubTaskStatus.RUNNING:
            task.status = SubTaskStatus.DONE
            found = [s for s in session.sources if task.id in s.found_by]
            kept = sum(s.status == SourceStatus.KEPT for s in found)
            task.note = f"{kept} kept, {len(found) - kept} excluded"


def _apply_search_results(
    deps: AgentDeps, session: ResearchSession, task: SubTask, results: list[SearchResult]
) -> list[Source]:
    """Run code rules, add new sources to the session, return the ones that need judging."""
    report = apply_rules(
        results,
        existing=session.sources,
        today=deps.today(),
        recency_days=session.settings.recency_days,
        config=deps.blueprint.filtering,
    )
    by_url = {normalize_url(s.url): s for s in session.sources}
    for duplicate in report.duplicates:
        existing = by_url.get(normalize_url(duplicate.url))
        if existing is not None and task.id not in existing.found_by:
            existing.found_by.append(task.id)

    to_judge: list[Source] = []
    rule_exclusions = []
    for outcome in report.outcomes:
        result = outcome.result
        source = Source(
            id=f"S{len(session.sources) + 1}",
            url=result.url,
            title=result.title or result.url,
            domain=domain_of(result.url),
            published_date=result.published_date,
            snippet=result.snippet,
            content=result.content,
            found_by=[task.id],
        )
        if outcome.exclusion_reason:
            source.status = SourceStatus.EXCLUDED
            source.exclusion = Exclusion(
                stage=ExclusionStage.RULE, reason=outcome.exclusion_reason, rule=outcome.rule
            )
            rule_exclusions.append(source)
        else:
            to_judge.append(source)
        session.sources.append(source)

    session.add_log(
        actor=Actor.AGENT,
        step="search",
        action=f"searched '{task.query}' ({task.search_mode})",
        decision=(
            f"{len(results)} results: {len(report.duplicates)} already known, "
            f"{len(rule_exclusions)} excluded by rules, {len(to_judge)} sent to relevance check"
        ),
        reason=task.title,
        details={"subtask_id": task.id, "query": task.query},
    )
    for source in rule_exclusions:
        assert source.exclusion is not None
        session.add_log(
            actor=Actor.AGENT,
            step="filter",
            action=f"excluded {source.id} ({source.domain})",
            decision="excluded by rule",
            reason=source.exclusion.reason,
            details={"source_id": source.id, "url": source.url, "title": source.title},
        )
    return to_judge


async def _judge_relevance(
    deps: AgentDeps, session: ResearchSession, task: SubTask, sources: list[Source]
) -> RelevanceOutput | None:
    """One LLM call judges all new sources from one search. None if the call failed."""
    limit = deps.blueprint.filtering.relevance_content_chars
    expected = {s.id for s in sources}
    try:
        return await call_llm_step(
            deps,
            session,
            "relevance",
            RelevanceOutput,
            values={
                "context": research_context(deps, session),
                "research_questions": research_questions_text(session),
                "search_purpose": f"{task.title} (query: {task.query})",
                "sources": "\n\n".join(
                    wrap_source(s, f"{s.snippet}\n\n{s.content[:limit]}") for s in sources
                ),
            },
            validate=lambda output: judgment_problems(output, expected),
        )
    except (StructuredOutputError, LLMError) as exc:
        session.add_log(
            actor=Actor.SYSTEM,
            step="relevance",
            action="relevance check failed",
            decision=f"kept {len(sources)} sources unjudged",
            reason=str(exc),
            details={"subtask_id": task.id},
        )
        return None


def _apply_judgments(
    session: ResearchSession, sources: list[Source], output: RelevanceOutput | None
) -> None:
    if output is None:
        return
    threshold = session.settings.relevance_threshold
    by_id = {s.id: s for s in sources}
    for judgment in output.judgments:
        source = by_id[judgment.source_id]
        source.relevance_score = judgment.score
        source.relevance_reason = judgment.reason
        if judgment.score < threshold:
            source.status = SourceStatus.EXCLUDED
            source.exclusion = Exclusion(
                stage=ExclusionStage.RELEVANCE,
                reason=f"low relevance ({judgment.score:.2f} < {threshold:.2f}): {judgment.reason}",
            )
        session.add_log(
            actor=Actor.AGENT,
            step="relevance",
            action=f"{'kept' if source.status == SourceStatus.KEPT else 'excluded'} {source.id} "
            f"({source.domain})",
            decision=f"relevance {judgment.score:.2f}",
            reason=judgment.reason,
            details={"source_id": source.id, "url": source.url, "title": source.title},
        )
