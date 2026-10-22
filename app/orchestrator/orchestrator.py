"""The orchestrator: runs one unit of work per call and applies the state machine.

`step()` never waits for the user. When a session needs input (questions, plan approval) or is
paused, `step()` does nothing and the driver (CLI or API) collects the input and calls
`handle_command()`. That keeps this class free of threads, sleeps and I/O to the user, and lets
tests drive a whole session by calling these two methods.
"""

from collections.abc import Awaitable, Callable

from app.llm.base import LLMError, StructuredOutputError
from app.memory.service import MemoryService
from app.models import (
    Actor,
    AddSubtask,
    AnswerQuestions,
    ApprovePlan,
    EditPlan,
    ExcludeSource,
    IncludeSource,
    Mode,
    Pause,
    ResearchSession,
    Resume,
    SetMode,
    SetRecency,
    SkipSubtask,
    Status,
    SubTask,
    SubTaskStatus,
    SubTaskType,
    UserCommand,
    utc_now,
)
from app.orchestrator import overrides
from app.orchestrator.budget import skip_searches_over_cost_cap
from app.orchestrator.deps import AgentDeps
from app.orchestrator.errors import CommandRejected
from app.orchestrator.scheduler import all_finished, ready_tasks
from app.orchestrator.state_machine import EventType, InvalidTransition, is_runnable, next_status
from app.orchestrator.steps.clarify import run_clarify
from app.orchestrator.steps.cross_check import run_cross_check
from app.orchestrator.steps.gap_check import run_gap_check
from app.orchestrator.steps.plan import run_plan
from app.orchestrator.steps.questions import (
    answer_question,
    auto_resolve_if_autonomous,
    skip_question,
)
from app.orchestrator.steps.search import run_searches
from app.orchestrator.steps.summarize import run_summarize
from app.orchestrator.steps.synthesize import run_synthesize

Handler = Callable[[ResearchSession], Awaitable[EventType]]


class Orchestrator:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        self._handlers: dict[Status, Handler] = {
            Status.CREATED: self._start,
            Status.CLARIFYING: self._clarify,
            Status.PLANNING: self._plan,
            Status.EXECUTING: self._execute,
            Status.GAP_CHECK: self._gap_check,
            Status.SYNTHESIZING: self._synthesize,
        }

    # --- Driving the session ------------------------------------------------------------------

    async def step(self, session: ResearchSession) -> ResearchSession:
        """Do one unit of work for the current status, then move to the next status."""
        if not is_runnable(session.status, session.paused):
            return session
        handler = self._handlers[session.status]
        try:
            event = await handler(session)
        except (StructuredOutputError, LLMError) as exc:
            session.error = str(exc)
            session.add_log(
                actor=Actor.SYSTEM,
                step=session.status.value,
                action="step failed",
                decision="session stopped",
                reason=str(exc),
            )
            event = EventType.FAILED
        self._transition(session, event)
        return session

    async def run_until_blocked(
        self,
        session: ResearchSession,
        on_step: Callable[[ResearchSession], None] | None = None,
    ) -> ResearchSession:
        """Keep stepping until the session finishes, fails, pauses or needs the user."""
        while is_runnable(session.status, session.paused):
            await self.step(session)
            if on_step is not None:
                on_step(session)
        return session

    async def handle_command(self, session: ResearchSession, command: UserCommand) -> None:
        """Apply a user action. Every accepted command is logged with actor=user."""
        match command:
            case AnswerQuestions():
                self._answer_questions(session, command)
            case ApprovePlan():
                if session.status != Status.AWAITING_PLAN_APPROVAL:
                    raise CommandRejected("there is no plan waiting for approval")
                self._log_user(session, "approved the plan")
                self._transition(session, EventType.PLAN_APPROVED)
            case Pause():
                session.paused = True
                self._log_user(session, "paused the session")
            case Resume():
                session.paused = False
                self._log_user(session, "resumed the session")
            case SetMode():
                self._set_mode(session, command)
            case EditPlan():
                self._after_override(session, overrides.edit_plan(session, command))
            case SkipSubtask():
                self._after_override(session, overrides.skip_subtask(session, command))
            case AddSubtask():
                result = overrides.add_subtask(session, command, self.deps.blueprint)
                self._after_override(session, result)
            case ExcludeSource():
                self._after_override(session, overrides.exclude_source(session, command))
            case IncludeSource():
                result = overrides.include_source(session, command, self.deps.blueprint)
                self._after_override(session, result)
            case SetRecency():
                result = overrides.set_recency(
                    session, command, self.deps.blueprint, self.deps.today()
                )
                self._after_override(session, result)
        session.updated_at = utc_now()

    def _after_override(self, session: ResearchSession, result: overrides.OverrideResult) -> None:
        """If the change touches finished work, go back and redo what depends on it: new tasks
        run, coverage is re-checked, and the report is rewritten."""
        if result.affects_findings and session.status in {Status.GAP_CHECK, Status.DONE}:
            self._transition(session, EventType.PLAN_CHANGED)

    def _set_mode(self, session: ResearchSession, command: SetMode) -> None:
        if session.status in {Status.DONE, Status.FAILED}:
            raise CommandRejected("the mode only affects a running session")
        if command.mode == session.mode:
            raise CommandRejected(f"the session is already in {command.mode} mode")
        session.mode = command.mode
        self._log_user(session, f"switched to {command.mode} mode")
        if command.mode != Mode.AUTONOMOUS:
            return
        # Autonomous means "don't wait for me": release whatever the agent is waiting on.
        if session.status == Status.AWAITING_PLAN_APPROVAL:
            session.add_log(
                actor=Actor.AGENT,
                step="plan",
                action="approved the plan automatically",
                reason="autonomous mode: the user is not reviewing plans",
            )
            self._transition(session, EventType.PLAN_APPROVED)
        elif session.status == Status.AWAITING_ANSWERS:
            from_gap_check = any(q.origin == "gap_check" for q in session.pending_questions())
            auto_resolve_if_autonomous(session)
            event = EventType.GAP_ANSWER_RECEIVED if from_gap_check else EventType.ANSWERS_RECEIVED
            self._transition(session, event)

    def _answer_questions(self, session: ResearchSession, command: AnswerQuestions) -> None:
        """Record answers; a None answer, or a question left out, counts as skipped."""
        if session.status != Status.AWAITING_ANSWERS:
            raise CommandRejected("there are no questions waiting for an answer")
        pending = session.pending_questions()
        known = {q.id for q in pending}
        unknown = set(command.answers) - known
        if unknown:
            raise CommandRejected(f"unknown or already answered questions: {sorted(unknown)}")
        from_gap_check = any(q.origin == "gap_check" for q in pending)
        for question in pending:
            answer = (command.answers.get(question.id) or "").strip()
            if answer:
                answer_question(session, question, answer)
            else:
                skip_question(session, question, Actor.USER)
        event = EventType.GAP_ANSWER_RECEIVED if from_gap_check else EventType.ANSWERS_RECEIVED
        self._transition(session, event)

    # --- State handlers -----------------------------------------------------------------------

    async def _start(self, session: ResearchSession) -> EventType:
        session.add_log(
            actor=Actor.AGENT,
            step="start",
            action="started research session",
            decision=f"mode: {session.mode}, recency window: {session.settings.recency_days} days",
            reason=session.topic,
        )
        if self.deps.memory is not None:
            self._recall(session, self.deps.memory)
        return EventType.STARTED

    def _recall(self, session: ResearchSession, memory: MemoryService) -> None:
        """Bring related past research into this session. It reaches every prompt through the
        shared context block, labeled 'from past research'."""
        session.related_memory = memory.recall(
            session.user_id, session.topic, exclude_session_id=session.id
        )
        if session.related_memory:
            session.add_log(
                actor=Actor.AGENT,
                step="memory",
                action=f"recalled {len(session.related_memory)} related past session(s)",
                decision="; ".join(
                    f'"{m.topic}" (similarity {m.similarity:.2f})' for m in session.related_memory
                ),
                reason="the planner will build on these findings instead of repeating them",
            )
        else:
            session.add_log(
                actor=Actor.AGENT, step="memory", action="no related past research found"
            )

    async def _clarify(self, session: ResearchSession) -> EventType:
        await run_clarify(self.deps, session)
        if auto_resolve_if_autonomous(session):
            return EventType.QUESTIONS_ASKED
        return EventType.NO_QUESTIONS

    async def _plan(self, session: ResearchSession) -> EventType:
        session.plan = await run_plan(self.deps, session)
        return EventType.PLAN_READY

    async def _execute(self, session: ResearchSession) -> EventType:
        assert session.plan is not None
        max_cost = self.deps.blueprint.limits.max_cost_usd
        skipped = skip_searches_over_cost_cap(session, max_cost)
        if skipped:
            session.add_log(
                actor=Actor.SYSTEM,
                step="budget",
                action=f"skipped {len(skipped)} pending search(es)",
                decision="continuing with sources already found",
                reason=f"session cost ${session.budget.cost_usd:.2f} passed the "
                f"${max_cost:.2f} cap",
                details={"skipped": [t.id for t in skipped]},
            )
        batch = ready_tasks(session.plan)
        searches = [t for t in batch if t.type == SubTaskType.SEARCH]
        if searches:
            await run_searches(self.deps, session, searches)
        for task in batch:
            if task.type != SubTaskType.SEARCH:
                await self._run_analysis_task(session, task)
        return EventType.ALL_TASKS_DONE if all_finished(session.plan) else EventType.BATCH_DONE

    async def _run_analysis_task(self, session: ResearchSession, task: SubTask) -> None:
        """Summarize / cross-check. A failure fails only this sub-task, not the session."""
        try:
            if task.type == SubTaskType.SUMMARIZE:
                await run_summarize(self.deps, session, task)
            elif task.type == SubTaskType.CROSS_CHECK:
                await run_cross_check(self.deps, session, task)
        except (StructuredOutputError, LLMError) as exc:
            task.status = SubTaskStatus.FAILED
            task.note = f"failed: {exc}"
            session.add_log(
                actor=Actor.SYSTEM,
                step=task.type.value,
                action=f"sub-task {task.id} failed",
                decision="continuing with the rest of the plan",
                reason=str(exc),
                details={"subtask_id": task.id},
            )

    async def _gap_check(self, session: ResearchSession) -> EventType:
        assert session.plan is not None
        if not all_finished(session.plan):
            # The user added work (e.g. a search, or a summary for a restored source) while the
            # agent was waiting; run it before judging coverage.
            session.add_log(
                actor=Actor.SYSTEM,
                step="gap_check",
                action="new sub-tasks are pending",
                decision="running them before reviewing coverage",
            )
            return EventType.PLAN_CHANGED
        decision = await run_gap_check(self.deps, session)
        if decision.verdict == "replan":
            return EventType.REPLAN
        if decision.verdict == "needs_user":
            return EventType.NEEDS_USER
        return EventType.SUFFICIENT

    async def _synthesize(self, session: ResearchSession) -> EventType:
        session.report = await run_synthesize(self.deps, session)
        if self.deps.memory is not None:
            item = self.deps.memory.remember(session)
            if item is not None:
                session.add_log(
                    actor=Actor.SYSTEM,
                    step="memory",
                    action="saved findings to long-term memory",
                    decision=f"{len(item.key_findings)} findings, "
                    f"{len(item.suggested_topics)} suggested topics",
                    reason=f"kept until {item.expires_at.date().isoformat()} "
                    f"({self.deps.memory.config.ttl_days}-day memory TTL)",
                )
        return EventType.REPORT_READY

    # --- Helpers ------------------------------------------------------------------------------

    def _transition(self, session: ResearchSession, event: EventType) -> None:
        try:
            new_status = next_status(session.status, event, session.mode)
        except InvalidTransition as exc:
            raise CommandRejected(str(exc)) from exc
        if new_status != session.status:
            session.add_log(
                actor=Actor.SYSTEM,
                step="state",
                action=f"{session.status} -> {new_status}",
                decision=event.value,
            )
        session.status = new_status
        session.updated_at = utc_now()

    def _log_user(self, session: ResearchSession, action: str, reason: str = "") -> None:
        session.add_log(actor=Actor.USER, step="override", action=action, reason=reason)
