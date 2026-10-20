from app.models import ResearchPlan, SubTaskType
from app.orchestrator.plan_validation import validate_plan
from app.orchestrator.steps.plan import PlanOutput, to_research_plan
from tests.helpers import search_task, simple_plan, summarize_task

ALL_TYPES = list(SubTaskType)


def check(plan: ResearchPlan | PlanOutput, **overrides: int) -> list[str]:
    if isinstance(plan, PlanOutput):
        plan = to_research_plan(plan)
    limits = {"max_subtasks": 10, "searches_remaining": 12} | overrides
    return validate_plan(plan, allowed_types=ALL_TYPES, **limits)


def test_valid_plan_has_no_problems() -> None:
    assert check(simple_plan()) == []


def test_search_needs_a_query() -> None:
    plan = simple_plan()
    plan.subtasks[0].query = "  "
    assert any("non-empty query" in p for p in check(plan))


def test_unknown_dependency() -> None:
    plan = simple_plan()
    plan.subtasks[2].depends_on = ["t1", "t9"]
    assert any("unknown sub-task 't9'" in p for p in check(plan))


def test_summarize_must_depend_on_searches() -> None:
    plan = simple_plan()
    plan.subtasks[3].depends_on = ["t1"]  # cross_check -> search is not allowed
    assert any("may only depend on summarize" in p for p in check(plan))


def test_search_must_not_have_dependencies() -> None:
    plan = simple_plan()
    plan.subtasks[1].depends_on = ["t1"]
    assert any("must not depend" in p for p in check(plan))


def test_every_research_question_needs_a_search() -> None:
    plan = simple_plan()
    plan.subtasks[1].research_question_ids = ["RQ1"]
    assert any("'RQ2' is not targeted" in p for p in check(plan))


def test_unknown_research_question() -> None:
    plan = simple_plan()
    plan.subtasks[0].research_question_ids = ["RQ1", "RQ7"]
    assert any("unknown research question 'RQ7'" in p for p in check(plan))


def test_every_search_must_be_summarized() -> None:
    plan = simple_plan()
    plan.subtasks[2].depends_on = ["t1"]
    assert any("'t2' is not summarized" in p for p in check(plan))


def test_too_many_subtasks() -> None:
    assert any("maximum is 3" in p for p in check(simple_plan(), max_subtasks=3))


def test_search_budget() -> None:
    assert any("only 1 are left" in p for p in check(simple_plan(), searches_remaining=1))


def test_duplicate_ids() -> None:
    plan = simple_plan()
    plan.subtasks.append(search_task("t1", "duplicate", ["RQ1"]))
    plan.subtasks.append(summarize_task("t5", ["t1"]))
    assert any("'t1' is used more than once" in p for p in check(plan))


def test_type_not_allowed_by_blueprint() -> None:
    plan = to_research_plan(simple_plan())
    problems = validate_plan(
        plan,
        allowed_types=[SubTaskType.SEARCH, SubTaskType.SUMMARIZE],
        max_subtasks=10,
        searches_remaining=12,
    )
    assert any("'cross_check', which is not allowed" in p for p in problems)


def test_plan_without_searches() -> None:
    plan = simple_plan()
    plan.subtasks = []
    problems = check(plan)
    assert any("at least one search" in p for p in problems)
