"""Human overrides: the user changing the plan, the sources or the date window mid-research.

Each function checks that the command fits the session's state (raising CommandRejected → HTTP 409
otherwise), applies the change, and logs it with actor=user, so the action log shows every human
decision next to the agent's. They return whether the change affects finished work: if so, and the
session is past execution, the orchestrator reopens it (coverage check → rewritten report).

The runner applies commands between steps, never in the middle of one, so these functions never
race with a running search or summary.
"""

from dataclasses import dataclass
from datetime import date

from app.blueprint import Blueprint
from app.filtering import recency_problem
from app.models import (
    Actor,
    AddSubtask,
    EditPlan,
    ExcludeSource,
    Exclusion,
    ExclusionStage,
    IncludeSource,
    Origin,
    ResearchSession,
    SetRecency,
    SkipSubtask,
    Source,
    SourceStatus,
    Status,
    SubTask,
    SubTaskStatus,
    SubTaskType,
)
from app.orchestrator.errors import CommandRejected
from app.orchestrator.plan_validation import validate_plan
from app.orchestrator.steps.gap_check import NewSearchOutput, build_replan_tasks, next_task_number

# Statuses in which the plan may change. During AWAITING_ANSWERS the agent is mid-conversation
# with the user, and before PLANNING there is no plan yet.
PLAN_CHANGEABLE = frozenset(
    {Status.AWAITING_PLAN_APPROVAL, Status.EXECUTING, Status.GAP_CHECK, Status.DONE}
)


@dataclass
class OverrideResult:
    affects_findings: bool = False  # True: finished work must be revisited (reopen if past it)


def _log(session: ResearchSession, action: str, decision: str = "", reason: str = "") -> None:
    session.add_log(
        actor=Actor.USER, step="override", action=action, decision=decision, reason=reason
    )


def _require_plan_changeable(session: ResearchSession) -> None:
    if session.plan is None or session.status not in PLAN_CHANGEABLE:
        raise CommandRejected(f"the plan can't be changed while the session is {session.status}")


def _require_not_failed(session: ResearchSession) -> None:
    if session.status == Status.FAILED:
        raise CommandRejected("the session has failed; start a new one")


def _pending_task(session: ResearchSession, subtask_id: str) -> SubTask:
    assert session.plan is not None
    task = session.plan.get_subtask(subtask_id)
    if task is None:
        raise CommandRejected(f"no sub-task {subtask_id}")
    if task.status != SubTaskStatus.PENDING:
        raise CommandRejected(
            f"sub-task {subtask_id} is {task.status}; only pending ones can change"
        )
    return task


def _source(session: ResearchSession, source_id: str) -> Source:
    source = session.get_source(source_id)
    if source is None:
        raise CommandRejected(f"no source {source_id}")
    return source


# --- Plan overrides --------------------------------------------------------------------------


def edit_plan(session: ResearchSession, command: EditPlan) -> OverrideResult:
    _require_plan_changeable(session)
    assert session.plan is not None
    tasks = [(_pending_task(session, edit.id), edit) for edit in command.edits]  # check all first
    for task, edit in tasks:
        if edit.query is not None:
            if task.type != SubTaskType.SEARCH:
                raise CommandRejected(f"sub-task {task.id} is not a search; it has no query")
            if len(edit.query.strip()) < 3:
                raise CommandRejected("a search query needs at least 3 characters")
    session.plan.version += 1
    for task, edit in tasks:
        if edit.query is not None and edit.query.strip() != task.query:
            _log(session, f"edited query of {task.id}", f'"{task.query}" → "{edit.query.strip()}"')
            task.query = edit.query.strip()
        if edit.title is not None and edit.title.strip() and edit.title.strip() != task.title:
            _log(session, f"renamed {task.id}", f'"{task.title}" → "{edit.title.strip()}"')
            task.title = edit.title.strip()
    return OverrideResult()


def skip_subtask(session: ResearchSession, command: SkipSubtask) -> OverrideResult:
    _require_plan_changeable(session)
    assert session.plan is not None
    task = _pending_task(session, command.subtask_id)
    task.status = SubTaskStatus.SKIPPED
    task.note = "skipped by the user"
    session.plan.version += 1
    _log(session, f"skipped {task.id}: {task.title}", "tasks after it still run on other sources")
    return OverrideResult()


def add_subtask(
    session: ResearchSession, command: AddSubtask, blueprint: Blueprint
) -> OverrideResult:
    _require_plan_changeable(session)
    assert session.plan is not None
    pending_searches = sum(
        t.type == SubTaskType.SEARCH and t.status == SubTaskStatus.PENDING
        for t in session.plan.subtasks
    )
    if session.budget.searches + pending_searches >= blueprint.limits.max_searches:
        raise CommandRejected(
            f"the search budget ({blueprint.limits.max_searches} per session) is used up"
        )
    search = NewSearchOutput(
        query=command.query.strip(),
        search_mode=command.search_mode,
        research_question_ids=command.research_question_ids,
        reason=command.title.strip() or f"Added by the user: {command.query.strip()}",
    )
    new_tasks = build_replan_tasks(
        session.plan, [search], blueprint.allowed_subtask_types, origin=Origin.USER
    )
    merged = session.plan.model_copy(deep=True)
    merged.subtasks += new_tasks
    problems = validate_plan(
        merged,
        allowed_types=blueprint.allowed_subtask_types,
        max_subtasks=len(merged.subtasks),
        searches_remaining=1,
        new_searches=1,
    )
    if problems:
        raise CommandRejected("; ".join(problems))
    session.plan.subtasks += new_tasks
    session.plan.version += 1
    _log(
        session,
        f'added search "{search.query}" ({search.search_mode})',
        f"new tasks: {', '.join(t.id for t in new_tasks)}",
    )
    return OverrideResult(affects_findings=True)


# --- Source overrides ------------------------------------------------------------------------


def exclude_source(session: ResearchSession, command: ExcludeSource) -> OverrideResult:
    _require_not_failed(session)
    source = _source(session, command.source_id)
    if source.status == SourceStatus.EXCLUDED:
        raise CommandRejected(f"{source.id} is already excluded")
    reason = (command.reason or "").strip() or "excluded by the user"
    source.status = SourceStatus.EXCLUDED
    source.exclusion = Exclusion(stage=ExclusionStage.USER, reason=reason)
    _log(
        session,
        f"excluded {source.id} ({source.domain})",
        "it won't be cited or compared"
        + (" — the report will be revised" if session.report else ""),
        reason,
    )
    return OverrideResult(affects_findings=True)


def include_source(
    session: ResearchSession, command: IncludeSource, blueprint: Blueprint
) -> OverrideResult:
    _require_not_failed(session)
    source = _source(session, command.source_id)
    if source.status == SourceStatus.KEPT or source.exclusion is None:
        raise CommandRejected(f"{source.id} is not excluded")
    was = f"was excluded ({source.exclusion.stage}): {source.exclusion.reason}"
    source.status = SourceStatus.KEPT
    source.exclusion = None
    _log(session, f"re-included {source.id} ({source.domain})", "kept again", was)
    add_summary_task_if_needed(session, [source], blueprint)
    return OverrideResult(affects_findings=True)


def set_recency(
    session: ResearchSession, command: SetRecency, blueprint: Blueprint, today: date
) -> OverrideResult:
    """Change the date window and re-check every source already found against it."""
    _require_not_failed(session)
    old = session.settings.recency_days
    if command.recency_days == old:
        raise CommandRejected(f"the window is already {old} days")
    session.settings.recency_days = command.recency_days
    policy = blueprint.filtering.unknown_date_policy

    newly_excluded: list[Source] = []
    restored: list[Source] = []
    for source in session.sources:
        problem = recency_problem(
            source.published_date,
            today=today,
            recency_days=command.recency_days,
            unknown_date_policy=policy,
        )
        if source.status == SourceStatus.KEPT and problem and source.published_date is not None:
            source.status = SourceStatus.EXCLUDED
            source.exclusion = Exclusion(
                stage=ExclusionStage.RULE,
                reason=f"{problem} (window changed by the user)",
                rule="recency",
            )
            newly_excluded.append(source)
        elif (
            source.status == SourceStatus.EXCLUDED
            and source.exclusion is not None
            and source.exclusion.rule == "recency"
            and problem is None
        ):
            # Excluded by date before the relevance judge ever saw it: kept, but say so.
            source.status = SourceStatus.KEPT
            source.exclusion = None
            source.relevance_reason = "restored when the date window widened; not relevance-checked"
            restored.append(source)

    _log(
        session,
        f"changed the date window from {old} to {command.recency_days} days",
        f"{len(newly_excluded)} source(s) now outside it, {len(restored)} restored",
        "already-found sources were re-checked against the new window; future searches use it too",
    )
    for source in newly_excluded:
        session.add_log(
            actor=Actor.AGENT,
            step="filter",
            action=f"excluded {source.id} ({source.domain})",
            decision="outside the new window",
            reason=source.exclusion.reason if source.exclusion else "",
        )
    if restored:
        add_summary_task_if_needed(session, restored, blueprint)
    return OverrideResult(affects_findings=bool(newly_excluded or restored))


def add_summary_task_if_needed(
    session: ResearchSession, sources: list[Source], blueprint: Blueprint
) -> SubTask | None:
    """Restored sources without a summary need one before they can be cited. Adds a summarize
    task over the searches that found them (unless a pending one already covers those)."""
    if session.plan is None:
        return None
    summarized = {s.source_id for s in session.summaries}
    needing = [s for s in sources if s.id not in summarized]
    if not needing:
        return None
    covered = {
        dep
        for t in session.plan.subtasks
        if t.type == SubTaskType.SUMMARIZE and t.status == SubTaskStatus.PENDING
        for dep in t.depends_on
    }
    search_ids = sorted({sid for s in needing for sid in s.found_by} - covered)
    if not search_ids:
        return None
    if len(session.summaries) >= blueprint.limits.max_sources_summarized:
        session.add_log(
            actor=Actor.SYSTEM,
            step="summarize",
            action="restored source(s) not summarized",
            decision="summary budget used up",
            reason="they are kept but can't be cited",
        )
        return None
    task = SubTask(
        id=f"t{next_task_number(session.plan)}",
        type=SubTaskType.SUMMARIZE,
        title="Summarize sources restored by the user",
        depends_on=search_ids,
        origin=Origin.USER,
    )
    session.plan.subtasks.append(task)
    session.plan.version += 1
    session.add_log(
        actor=Actor.AGENT,
        step="plan",
        action=f"added {task.id} to summarize restored sources",
        decision=", ".join(s.id for s in needing),
    )
    return task
