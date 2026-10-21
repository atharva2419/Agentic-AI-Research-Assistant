"""GAP_CHECK: review coverage per research question and decide what to do next.

The LLM picks a verdict; code decides which verdicts are even allowed (budgets, mode), validates
the new searches against the plan rules, and builds the new sub-tasks itself.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.models import (
    Actor,
    Mode,
    Origin,
    ResearchPlan,
    ResearchSession,
    SearchMode,
    SourceStatus,
    SubTask,
    SubTaskType,
)
from app.orchestrator.deps import AgentDeps
from app.orchestrator.plan_validation import validate_plan
from app.orchestrator.steps.common import call_llm_step, research_context
from app.orchestrator.steps.questions import QuestionOutput, add_questions

Verdict = Literal["sufficient", "replan", "needs_user"]


class GapOutput(BaseModel):
    research_question_id: str
    description: str


class NewSearchOutput(BaseModel):
    query: str
    search_mode: SearchMode
    research_question_ids: list[str]
    reason: str


class GapCheckOutput(BaseModel):
    verdict: Verdict
    reasoning: str
    gaps: list[GapOutput]
    new_searches: list[NewSearchOutput]
    question: QuestionOutput | None


@dataclass(frozen=True)
class GapOptions:
    """Which verdicts code allows right now, and why the others are off."""

    can_replan: bool
    can_ask: bool
    max_new_searches: int
    notes: list[str]

    @property
    def allowed(self) -> list[Verdict]:
        allowed: list[Verdict] = ["sufficient"]
        if self.can_replan:
            allowed.append("replan")
        if self.can_ask:
            allowed.append("needs_user")
        return allowed


def gap_options(deps: AgentDeps, session: ResearchSession) -> GapOptions:
    limits = deps.blueprint.limits
    budget = session.budget
    searches_left = limits.max_searches - budget.searches
    notes = []
    can_replan = True
    if budget.replans >= limits.max_replans:
        can_replan = False
        notes.append(f"replan unavailable: all {limits.max_replans} replans used")
    elif searches_left <= 0:
        can_replan = False
        notes.append("replan unavailable: search budget used up")
    elif budget.cost_usd >= limits.replan_cost_ceiling_usd:
        can_replan = False
        notes.append(
            f"replan unavailable: session cost ${budget.cost_usd:.2f} is past the "
            f"${limits.replan_cost_ceiling_usd:.2f} replan ceiling"
        )
    can_ask = budget.gap_questions_asked < limits.max_gap_questions
    if session.mode == Mode.AUTONOMOUS:
        can_ask = False
        notes.append("needs_user unavailable: autonomous mode, the user is not waiting")
    elif not can_ask:
        notes.append("needs_user unavailable: the user was already asked during this session")
    return GapOptions(
        can_replan=can_replan,
        can_ask=can_ask,
        max_new_searches=min(limits.max_new_searches_per_replan, max(searches_left, 0)),
        notes=notes,
    )


def next_task_number(plan: ResearchPlan) -> int:
    numbers = [int(t.id[1:]) for t in plan.subtasks if t.id[1:].isdigit()]
    return max(numbers, default=0) + 1


def build_replan_tasks(
    plan: ResearchPlan, searches: list[NewSearchOutput], allowed: list[SubTaskType]
) -> list[SubTask]:
    """New search tasks, one summarize task over them, and a cross-check of new vs. existing."""
    n = next_task_number(plan)
    new: list[SubTask] = []
    for s in searches:
        new.append(
            SubTask(
                id=f"t{n}",
                type=SubTaskType.SEARCH,
                title=s.reason,
                query=s.query,
                search_mode=s.search_mode,
                research_question_ids=s.research_question_ids,
                origin=Origin.REPLAN,
            )
        )
        n += 1
    summarize = SubTask(
        id=f"t{n}",
        type=SubTaskType.SUMMARIZE,
        title="Summarize sources from follow-up searches",
        depends_on=[t.id for t in new],
        origin=Origin.REPLAN,
    )
    new.append(summarize)
    if SubTaskType.CROSS_CHECK in allowed:
        earlier = [t.id for t in plan.subtasks if t.type == SubTaskType.SUMMARIZE]
        new.append(
            SubTask(
                id=f"t{n + 1}",
                type=SubTaskType.CROSS_CHECK,
                title="Cross-check follow-up sources against earlier ones",
                focus="Do the new sources confirm or contradict the earlier findings?",
                depends_on=[summarize.id, *earlier],
                origin=Origin.REPLAN,
            )
        )
    return new


def gap_problems(
    output: GapCheckOutput, options: GapOptions, deps: AgentDeps, session: ResearchSession
) -> list[str]:
    assert session.plan is not None
    problems: list[str] = []
    if output.verdict not in options.allowed:
        problems.append(
            f"verdict '{output.verdict}' is not available now; choose one of {options.allowed}"
        )
        return problems
    if output.verdict == "replan":
        if not output.new_searches:
            problems.append("a replan needs at least one new search")
        if len(output.new_searches) > options.max_new_searches:
            problems.append(f"at most {options.max_new_searches} new searches are allowed")
        merged = session.plan.model_copy(deep=True)
        merged.subtasks += build_replan_tasks(
            session.plan, output.new_searches, deps.blueprint.allowed_subtask_types
        )
        problems += validate_plan(
            merged,
            allowed_types=deps.blueprint.allowed_subtask_types,
            max_subtasks=len(merged.subtasks),
            searches_remaining=options.max_new_searches,
            new_searches=len(output.new_searches),
        )
    elif output.new_searches:
        problems.append("new_searches must be empty unless the verdict is 'replan'")
    if output.verdict == "needs_user" and output.question is None:
        problems.append("verdict 'needs_user' needs a question")
    if output.verdict != "needs_user" and output.question is not None:
        problems.append("question must be null unless the verdict is 'needs_user'")
    return problems


def coverage_text(session: ResearchSession) -> str:
    """What was found per research question, compact enough for one prompt."""
    assert session.plan is not None
    summaries = {s.source_id: s for s in session.summaries}
    lines = []
    for rq in session.plan.research_questions:
        lines.append(f"{rq.id}: {rq.text}")
        searches = [
            t
            for t in session.plan.subtasks
            if t.type == SubTaskType.SEARCH and rq.id in t.research_question_ids
        ]
        search_ids = {t.id for t in searches}
        for t in searches:
            lines.append(f'  search {t.id} "{t.query}" ({t.status}: {t.note or "no results"})')
        found = [s for s in session.sources if search_ids & set(s.found_by)]
        kept = [s for s in found if s.status == SourceStatus.KEPT]
        summarized = [s for s in kept if s.id in summaries]
        lines.append(
            f"  sources: {len(found)} found, {len(kept)} kept, {len(summarized)} summarized"
        )
        for s in summarized:
            date = s.published_date.isoformat() if s.published_date else "date unknown"
            takeaways = "; ".join(summaries[s.id].key_takeaways[:2])
            lines.append(f"    - {s.id} ({s.domain}, {date}): {takeaways}")
        lines.append("")
    if session.contradictions:
        lines.append("Contradictions found so far:")
        lines += [f"- {c.topic}: {c.source_a} vs {c.source_b}" for c in session.contradictions]
    return "\n".join(lines).strip()


@dataclass
class GapDecision:
    verdict: Verdict
    new_tasks: list[SubTask]


async def run_gap_check(deps: AgentDeps, session: ResearchSession) -> GapDecision:
    assert session.plan is not None
    options = gap_options(deps, session)
    if options.allowed == ["sufficient"]:
        session.add_log(
            actor=Actor.SYSTEM,
            step="gap_check",
            action="skipped coverage review",
            decision="proceeding to the report",
            reason="; ".join(options.notes),
        )
        return GapDecision(verdict="sufficient", new_tasks=[])

    option_lines = [f"Allowed verdicts: {', '.join(options.allowed)}."]
    if options.can_replan:
        option_lines.append(f"A replan may add at most {options.max_new_searches} new searches.")
    option_lines += [f"Note: {n}." for n in options.notes]

    output = await call_llm_step(
        deps,
        session,
        "gap_check",
        GapCheckOutput,
        values={
            "context": research_context(deps, session),
            "coverage": coverage_text(session),
            "options": "\n".join(option_lines),
        },
        validate=lambda out: gap_problems(out, options, deps, session),
    )

    gaps = "; ".join(f"{g.research_question_id}: {g.description}" for g in output.gaps)
    if output.verdict == "replan":
        new_tasks = build_replan_tasks(
            session.plan, output.new_searches, deps.blueprint.allowed_subtask_types
        )
        session.plan.subtasks += new_tasks
        session.plan.version += 1
        session.budget.replans += 1
        session.add_log(
            actor=Actor.AGENT,
            step="gap_check",
            action=f"replanned (plan v{session.plan.version})",
            decision="new searches: " + ", ".join(f'"{s.query}"' for s in output.new_searches),
            reason=f"{output.reasoning} Gaps: {gaps}" if gaps else output.reasoning,
            details={"new_subtasks": [t.model_dump(mode="json") for t in new_tasks]},
        )
        return GapDecision(verdict="replan", new_tasks=new_tasks)

    if output.verdict == "needs_user":
        assert output.question is not None
        session.budget.gap_questions_asked += 1
        session.add_log(
            actor=Actor.AGENT,
            step="gap_check",
            action="coverage depends on what the user wants",
            decision="asking one question",
            reason=output.reasoning,
        )
        add_questions(session, [output.question], origin="gap_check")
        return GapDecision(verdict="needs_user", new_tasks=[])

    session.add_log(
        actor=Actor.AGENT,
        step="gap_check",
        action="coverage is sufficient",
        decision="proceeding to the report",
        reason=f"{output.reasoning} Remaining gaps: {gaps}" if gaps else output.reasoning,
    )
    return GapDecision(verdict="sufficient", new_tasks=[])
