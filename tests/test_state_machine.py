import pytest

from app.models import Mode, Status
from app.orchestrator.state_machine import (
    TRANSITIONS,
    EventType,
    InvalidTransition,
    is_runnable,
    next_status,
)


@pytest.mark.parametrize(("start", "event"), list(TRANSITIONS))
def test_every_table_row(start: Status, event: EventType) -> None:
    assert next_status(start, event, Mode.AUTONOMOUS) == TRANSITIONS[(start, event)]


def test_plan_ready_waits_for_approval_in_supervised_mode() -> None:
    assert (
        next_status(Status.PLANNING, EventType.PLAN_READY, Mode.SUPERVISED)
        == Status.AWAITING_PLAN_APPROVAL
    )


def test_plan_ready_executes_directly_in_autonomous_mode() -> None:
    assert next_status(Status.PLANNING, EventType.PLAN_READY, Mode.AUTONOMOUS) == Status.EXECUTING


@pytest.mark.parametrize("status", [s for s in Status if s not in {Status.DONE, Status.FAILED}])
def test_any_active_status_can_fail(status: Status) -> None:
    assert next_status(status, EventType.FAILED, Mode.AUTONOMOUS) == Status.FAILED


@pytest.mark.parametrize("status", [Status.DONE, Status.FAILED])
def test_terminal_states_accept_nothing(status: Status) -> None:
    with pytest.raises(InvalidTransition):
        next_status(status, EventType.STARTED, Mode.AUTONOMOUS)


def test_event_not_allowed_in_state() -> None:
    with pytest.raises(InvalidTransition):
        next_status(Status.CREATED, EventType.REPORT_READY, Mode.AUTONOMOUS)


def test_is_runnable() -> None:
    assert is_runnable(Status.EXECUTING, paused=False)
    assert not is_runnable(Status.EXECUTING, paused=True)
    assert not is_runnable(Status.AWAITING_PLAN_APPROVAL, paused=False)
    assert not is_runnable(Status.DONE, paused=False)
