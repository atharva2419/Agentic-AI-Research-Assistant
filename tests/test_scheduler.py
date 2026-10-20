from app.models import SubTaskStatus
from app.orchestrator.scheduler import all_finished, ready_tasks
from app.orchestrator.steps.plan import to_research_plan
from tests.helpers import simple_plan


def test_only_searches_are_ready_at_start() -> None:
    plan = to_research_plan(simple_plan())
    assert [t.id for t in ready_tasks(plan)] == ["t1", "t2"]


def test_summarize_waits_for_all_its_searches() -> None:
    plan = to_research_plan(simple_plan())
    plan.subtasks[0].status = SubTaskStatus.DONE
    assert [t.id for t in ready_tasks(plan)] == ["t2"]
    plan.subtasks[1].status = SubTaskStatus.DONE
    assert [t.id for t in ready_tasks(plan)] == ["t3"]


def test_skipped_or_failed_dependencies_do_not_block() -> None:
    plan = to_research_plan(simple_plan())
    plan.subtasks[0].status = SubTaskStatus.FAILED
    plan.subtasks[1].status = SubTaskStatus.SKIPPED
    assert [t.id for t in ready_tasks(plan)] == ["t3"]


def test_all_finished() -> None:
    plan = to_research_plan(simple_plan())
    assert not all_finished(plan)
    for task in plan.subtasks:
        task.status = SubTaskStatus.DONE
    assert all_finished(plan)
    assert ready_tasks(plan) == []
