"""The session cost cap. Search counts are enforced by plan validation; summaries by the
summary budget; this module handles the overall spend."""

from app.models import ResearchSession, SubTask, SubTaskStatus, SubTaskType


def skip_searches_over_cost_cap(session: ResearchSession, max_cost_usd: float) -> list[SubTask]:
    """Past the soft cost cap, pending searches are skipped. Summaries of what was already found
    and the final report still run, so the user always gets a report. Returns skipped tasks."""
    if session.plan is None or session.budget.cost_usd < max_cost_usd:
        return []
    skipped = [
        t
        for t in session.plan.subtasks
        if t.type == SubTaskType.SEARCH and t.status == SubTaskStatus.PENDING
    ]
    for t in skipped:
        t.status = SubTaskStatus.SKIPPED
        t.note = f"skipped: session cost passed ${max_cost_usd:.2f}"
    return skipped
