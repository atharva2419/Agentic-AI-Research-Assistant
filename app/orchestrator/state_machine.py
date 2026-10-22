"""The research session state machine: which status follows which event.

Pure functions only, no I/O. Step handlers do the work and report what happened as an `EventType`;
this module decides the next status. Decisions that depend on budgets (e.g. "replan or stop?") are
made by the handler when it picks the event, so this table stays a simple lookup.
"""

from enum import StrEnum

from app.models import Mode, Status


class EventType(StrEnum):
    STARTED = "started"
    QUESTIONS_ASKED = "questions_asked"
    NO_QUESTIONS = "no_questions"
    ANSWERS_RECEIVED = "answers_received"  # answers to the opening clarifying questions
    GAP_ANSWER_RECEIVED = "gap_answer_received"  # answer to a question asked by the gap check
    PLAN_READY = "plan_ready"
    PLAN_APPROVED = "plan_approved"
    BATCH_DONE = "batch_done"
    ALL_TASKS_DONE = "all_tasks_done"
    REPLAN = "replan"
    NEEDS_USER = "needs_user"
    SUFFICIENT = "sufficient"
    REPORT_READY = "report_ready"
    PLAN_CHANGED = "plan_changed"  # a user override created work or changed the evidence
    FAILED = "failed"


class InvalidTransition(Exception):
    pass


TERMINAL = frozenset({Status.DONE, Status.FAILED})
WAITING_FOR_USER = frozenset({Status.AWAITING_ANSWERS, Status.AWAITING_PLAN_APPROVAL})

TRANSITIONS: dict[tuple[Status, EventType], Status] = {
    (Status.CREATED, EventType.STARTED): Status.CLARIFYING,
    (Status.CLARIFYING, EventType.QUESTIONS_ASKED): Status.AWAITING_ANSWERS,
    (Status.CLARIFYING, EventType.NO_QUESTIONS): Status.PLANNING,
    (Status.AWAITING_ANSWERS, EventType.ANSWERS_RECEIVED): Status.PLANNING,
    # After a mid-research question, re-check coverage with the answer instead of re-planning
    # from scratch, so finished work is kept.
    (Status.AWAITING_ANSWERS, EventType.GAP_ANSWER_RECEIVED): Status.GAP_CHECK,
    # (PLANNING, PLAN_READY) depends on the mode: see next_status().
    (Status.AWAITING_PLAN_APPROVAL, EventType.PLAN_APPROVED): Status.EXECUTING,
    (Status.EXECUTING, EventType.BATCH_DONE): Status.EXECUTING,
    (Status.EXECUTING, EventType.ALL_TASKS_DONE): Status.GAP_CHECK,
    (Status.GAP_CHECK, EventType.REPLAN): Status.EXECUTING,
    (Status.GAP_CHECK, EventType.NEEDS_USER): Status.AWAITING_ANSWERS,
    (Status.GAP_CHECK, EventType.SUFFICIENT): Status.SYNTHESIZING,
    (Status.SYNTHESIZING, EventType.REPORT_READY): Status.DONE,
    (Status.GAP_CHECK, EventType.PLAN_CHANGED): Status.EXECUTING,
}

# A finished session can be reopened by a user override (e.g. excluding a source from the report):
# it goes back to EXECUTING, then through the coverage check to a rewritten report. FAILED is final.
REOPEN: dict[tuple[Status, EventType], Status] = {
    (Status.DONE, EventType.PLAN_CHANGED): Status.EXECUTING,
}


def next_status(status: Status, event: EventType, mode: Mode) -> Status:
    """Return the status that follows `event` in `status`. Raises InvalidTransition otherwise."""
    if (status, event) in REOPEN:
        return REOPEN[(status, event)]
    if status in TERMINAL:
        raise InvalidTransition(f"session is already {status}; got event {event}")
    if event == EventType.FAILED:
        return Status.FAILED
    if status == Status.PLANNING and event == EventType.PLAN_READY:
        if mode == Mode.SUPERVISED:
            return Status.AWAITING_PLAN_APPROVAL
        return Status.EXECUTING
    try:
        return TRANSITIONS[(status, event)]
    except KeyError:
        raise InvalidTransition(f"event {event} is not allowed in status {status}") from None


def is_runnable(status: Status, paused: bool) -> bool:
    """True if the orchestrator can do work now without waiting for the user."""
    return not paused and status not in TERMINAL and status not in WAITING_FOR_USER
