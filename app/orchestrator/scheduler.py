"""Decide which sub-tasks can run now."""

from app.models import ResearchPlan, SubTask, SubTaskStatus

FINISHED = frozenset({SubTaskStatus.DONE, SubTaskStatus.SKIPPED, SubTaskStatus.FAILED})


def ready_tasks(plan: ResearchPlan) -> list[SubTask]:
    """Pending sub-tasks whose dependencies have all finished, in plan order.

    A skipped or failed dependency still counts as finished: dependents run on whatever sources
    exist, rather than the whole plan stalling.
    """
    status = {t.id: t.status for t in plan.subtasks}
    return [
        t
        for t in plan.subtasks
        if t.status == SubTaskStatus.PENDING
        and all(status.get(dep) in FINISHED for dep in t.depends_on)
    ]


def all_finished(plan: ResearchPlan) -> bool:
    return all(t.status in FINISHED for t in plan.subtasks)
