"""Code checks on a research plan, run before anything executes.

Problems are returned as plain sentences so they can be sent back to the LLM in the retry loop.

Dependencies are layered by type: `summarize` may only depend on `search` tasks and `cross_check`
only on `summarize` tasks. That makes cycles impossible by construction, so no cycle detection is
needed.
"""

from collections import Counter

from app.models import ResearchPlan, SubTask, SubTaskType

ALLOWED_DEPENDENCY_TYPE: dict[SubTaskType, SubTaskType | None] = {
    SubTaskType.SEARCH: None,  # searches are independent
    SubTaskType.SUMMARIZE: SubTaskType.SEARCH,
    SubTaskType.CROSS_CHECK: SubTaskType.SUMMARIZE,
}


def validate_plan(
    plan: ResearchPlan,
    *,
    allowed_types: list[SubTaskType],
    max_subtasks: int,
    searches_remaining: int,
    new_searches: int | None = None,
) -> list[str]:
    """Return a list of problems with `plan` (empty if it is valid).

    `new_searches` is how many search tasks will cost budget; it defaults to all searches in the
    plan (first plan) and is smaller when validating a replan that keeps finished searches.
    """
    problems: list[str] = []
    tasks = plan.subtasks
    by_id = {t.id: t for t in tasks}

    rq_ids = [q.id for q in plan.research_questions]
    if not rq_ids:
        problems.append("the plan needs at least one research question")
    for rq_id, count in Counter(rq_ids).items():
        if count > 1:
            problems.append(f"research question id '{rq_id}' is used more than once")

    for task_id, count in Counter(t.id for t in tasks).items():
        if count > 1:
            problems.append(f"sub-task id '{task_id}' is used more than once")

    if len(tasks) > max_subtasks:
        problems.append(f"the plan has {len(tasks)} sub-tasks; the maximum is {max_subtasks}")

    searches = [t for t in tasks if t.type == SubTaskType.SEARCH]
    if not searches:
        problems.append("the plan needs at least one search sub-task")
    cost = len(searches) if new_searches is None else new_searches
    if cost > searches_remaining:
        problems.append(
            f"the plan needs {cost} new searches but only {searches_remaining} are left in the "
            "budget; use fewer, broader searches"
        )

    for task in tasks:
        if task.type not in allowed_types:
            problems.append(f"sub-task '{task.id}' has type '{task.type}', which is not allowed")
            continue
        if task.type == SubTaskType.SEARCH and not (task.query and task.query.strip()):
            problems.append(f"search sub-task '{task.id}' needs a non-empty query")
        for rq_id in task.research_question_ids:
            if rq_id not in rq_ids:
                problems.append(
                    f"sub-task '{task.id}' refers to unknown research question '{rq_id}'"
                )
        problems.extend(_dependency_problems(task.id, task.type, task.depends_on, by_id))

    for rq_id in set(rq_ids):
        if not any(rq_id in s.research_question_ids for s in searches):
            problems.append(f"research question '{rq_id}' is not targeted by any search sub-task")

    if SubTaskType.SUMMARIZE in allowed_types:
        summarized = {dep for t in tasks if t.type == SubTaskType.SUMMARIZE for dep in t.depends_on}
        for search in searches:
            if search.id not in summarized:
                problems.append(
                    f"search sub-task '{search.id}' is not summarized by any summarize sub-task"
                )

    return problems


def _dependency_problems(
    task_id: str,
    task_type: SubTaskType,
    depends_on: list[str],
    by_id: dict[str, SubTask],
) -> list[str]:
    required = ALLOWED_DEPENDENCY_TYPE[task_type]
    if required is None:
        if depends_on:
            return [f"{task_type} sub-task '{task_id}' must not depend on other sub-tasks"]
        return []
    if not depends_on:
        return [f"{task_type} sub-task '{task_id}' must depend on at least one {required} sub-task"]
    problems = []
    for dep in depends_on:
        target = by_id.get(dep)
        if target is None:
            problems.append(f"sub-task '{task_id}' depends on unknown sub-task '{dep}'")
        elif target.type != required:
            problems.append(
                f"{task_type} sub-task '{task_id}' may only depend on {required} sub-tasks, "
                f"but '{dep}' is {target.type}"
            )
    return problems
