"""PLANNING: the LLM breaks the topic into research questions and typed sub-tasks."""

from pydantic import BaseModel

from app.models import (
    Actor,
    Origin,
    ResearchPlan,
    ResearchQuestion,
    ResearchSession,
    SearchMode,
    SubTask,
    SubTaskType,
)
from app.orchestrator.deps import AgentDeps
from app.orchestrator.plan_validation import validate_plan
from app.orchestrator.steps.common import call_llm_step, research_context

# --- LLM output schema (what the model fills in; code adds status, origin, version) ---


class PlannedQuestion(BaseModel):
    id: str
    text: str


class PlannedSubTask(BaseModel):
    id: str
    type: SubTaskType
    title: str
    query: str | None
    search_mode: SearchMode
    focus: str | None
    research_question_ids: list[str]
    depends_on: list[str]


class PlanOutput(BaseModel):
    objective: str
    research_questions: list[PlannedQuestion]
    subtasks: list[PlannedSubTask]
    rationale: str
    # A wider date window when the user's framing needs older evidence (e.g. "since 2022").
    # null = keep the current window. Code only ever widens, never narrows the user's choice.
    recency_days: int | None
    recency_reason: str


MAX_RECENCY_DAYS = 3650


def recency_problems(output: PlanOutput, current_days: int) -> list[str]:
    if output.recency_days is None:
        return []
    problems = []
    if not 1 <= output.recency_days <= MAX_RECENCY_DAYS:
        problems.append(f"recency_days must be between 1 and {MAX_RECENCY_DAYS}, or null")
    if output.recency_days > current_days and not output.recency_reason.strip():
        problems.append("recency_reason must explain why the date window should be wider")
    return problems


def apply_recency_proposal(session: ResearchSession, output: PlanOutput) -> None:
    """Widen the window if the planner asks for it. Never narrow it: a tighter window than the
    user chose would silently drop evidence they expect. The change is logged as an agent
    decision, and the user can change it back with the date-window control."""
    proposed = output.recency_days
    current = session.settings.recency_days
    if proposed is None or proposed <= current:
        return
    session.settings.recency_days = min(proposed, MAX_RECENCY_DAYS)
    session.add_log(
        actor=Actor.AGENT,
        step="plan",
        action=f"widened the date window from {current} to {session.settings.recency_days} days",
        decision="older sources will be kept by the date rule",
        reason=output.recency_reason,
    )


def to_research_plan(output: PlanOutput, version: int = 1) -> ResearchPlan:
    return ResearchPlan(
        version=version,
        objective=output.objective,
        research_questions=[
            ResearchQuestion(id=q.id, text=q.text) for q in output.research_questions
        ],
        subtasks=[
            SubTask(
                id=t.id,
                type=t.type,
                title=t.title,
                query=t.query,
                search_mode=t.search_mode,
                focus=t.focus,
                research_question_ids=t.research_question_ids,
                depends_on=t.depends_on,
                origin=Origin.PLANNER,
            )
            for t in output.subtasks
        ],
        rationale=output.rationale,
    )


async def run_plan(deps: AgentDeps, session: ResearchSession) -> ResearchPlan:
    limits = deps.blueprint.limits
    allowed = deps.blueprint.allowed_subtask_types
    searches_remaining = limits.max_searches - session.budget.searches

    def validate(output: PlanOutput) -> list[str]:
        return validate_plan(
            to_research_plan(output),
            allowed_types=allowed,
            max_subtasks=limits.max_subtasks,
            searches_remaining=searches_remaining,
        ) + recency_problems(output, session.settings.recency_days)

    output = await call_llm_step(
        deps,
        session,
        "plan",
        PlanOutput,
        values={
            "context": research_context(deps, session),
            "allowed_types": ", ".join(allowed),
            "max_subtasks": str(limits.max_subtasks),
            "max_searches": str(searches_remaining),
        },
        validate=validate,
    )
    version = session.plan.version + 1 if session.plan else 1
    plan = to_research_plan(output, version=version)
    apply_recency_proposal(session, output)

    session.add_log(
        actor=Actor.AGENT,
        step="plan",
        action=f"created research plan v{plan.version}",
        decision=(
            f"{len(plan.research_questions)} research questions, {len(plan.subtasks)} sub-tasks "
            f"({sum(t.type == SubTaskType.SEARCH for t in plan.subtasks)} searches)"
        ),
        reason=plan.rationale,
        details={
            "objective": plan.objective,
            "research_questions": [q.model_dump() for q in plan.research_questions],
            "subtasks": [
                {"id": t.id, "type": t.type, "title": t.title, "query": t.query}
                for t in plan.subtasks
            ],
        },
    )
    return plan
