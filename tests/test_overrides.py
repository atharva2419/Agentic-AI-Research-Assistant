"""Phase 6: human overrides of the plan, sources, date window and mode."""

from datetime import date

import pytest

from app.llm.fake import FakeLLM
from app.models import (
    Actor,
    AddSubtask,
    AnswerQuestions,
    EditPlan,
    ExcludeSource,
    ExclusionStage,
    IncludeSource,
    Mode,
    Origin,
    ResearchSession,
    SearchMode,
    SetMode,
    SetRecency,
    SkipSubtask,
    SourceStatus,
    Status,
    SubTaskEdit,
    SubTaskStatus,
    SubTaskType,
)
from app.orchestrator.errors import CommandRejected
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.state_machine import EventType, next_status
from app.search.fake import FakeSearch
from tests.helpers import (
    CLEAR_TOPIC,
    NO_CONTRADICTIONS,
    SUFFICIENT,
    judge_all,
    make_deps,
    make_session,
    result,
    simple_plan,
    summary_for_prompt,
    synthesis_citing,
)

SEARCHES = {
    "AI newsroom adoption": [
        result("https://a.com/adoption", published=date(2026, 6, 1)),
        result("https://old.com/2025", published=date(2025, 3, 1)),  # outside 365 days
    ],
    "AI journalism jobs": [result("https://b.com/jobs", published=date(2026, 2, 1))],
    "edited query": [result("https://e.com/edited")],
    "user added query": [result("https://u.com/added")],
}


def search() -> FakeSearch:
    return FakeSearch(results=SEARCHES)


def llm(*, synth: int = 1, gaps: int = 1, summaries: int = 4) -> FakeLLM:
    fake = FakeLLM()
    fake.add("clarify", CLEAR_TOPIC)
    fake.add("plan", simple_plan())
    fake.add("relevance", *[judge_all()] * 4)
    fake.add("summarize", *[summary_for_prompt] * summaries)
    fake.add("cross_check", *[NO_CONTRADICTIONS] * 3)
    fake.add("gap_check", *[SUFFICIENT] * gaps)
    fake.add("synthesize", *[synthesis_citing(["S1"])] * synth)
    return fake


async def awaiting_approval(fake: FakeLLM) -> tuple[Orchestrator, ResearchSession]:
    orchestrator = Orchestrator(make_deps(fake, search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    assert session.status == Status.AWAITING_PLAN_APPROVAL
    return orchestrator, session


async def finished(fake: FakeLLM) -> tuple[Orchestrator, ResearchSession]:
    orchestrator = Orchestrator(make_deps(fake, search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.AUTONOMOUS))
    assert session.status == Status.DONE
    return orchestrator, session


def user_actions(session: ResearchSession) -> list[str]:
    return [e.action for e in session.log if e.actor == Actor.USER]


# --- Plan overrides ----------------------------------------------------------------------------


async def test_edit_query_before_approval_is_used_by_the_search() -> None:
    fake_search = search()
    orchestrator = Orchestrator(make_deps(llm(), fake_search))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    await orchestrator.handle_command(
        session, EditPlan(edits=[SubTaskEdit(id="t1", query="edited query")])
    )
    assert session.plan is not None and session.plan.version == 2
    assert "edited query of t1" in user_actions(session)
    await orchestrator.handle_command(session, SetMode(mode=Mode.AUTONOMOUS))
    await orchestrator.run_until_blocked(session)
    assert "edited query" in [q.query for q in fake_search.queries]


async def test_edit_rejects_finished_tasks_and_non_search_queries() -> None:
    orchestrator, session = await awaiting_approval(llm())
    with pytest.raises(CommandRejected, match="not a search"):
        await orchestrator.handle_command(
            session, EditPlan(edits=[SubTaskEdit(id="t3", query="x y z")])
        )
    _, done = await finished(llm())
    with pytest.raises(CommandRejected, match="only pending"):
        await orchestrator.handle_command(done, EditPlan(edits=[SubTaskEdit(id="t1", title="x")]))


async def test_skip_subtask_means_it_never_runs() -> None:
    fake_search = search()
    orchestrator = Orchestrator(make_deps(llm(), fake_search))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    await orchestrator.handle_command(session, SkipSubtask(subtask_id="t2"))
    await orchestrator.handle_command(session, SetMode(mode=Mode.AUTONOMOUS))
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE
    assert [q.query for q in fake_search.queries] == ["AI newsroom adoption"]
    assert session.plan is not None
    assert session.plan.get_subtask("t2").status == SubTaskStatus.SKIPPED  # type: ignore[union-attr]


async def test_add_search_builds_search_summarize_and_cross_check() -> None:
    orchestrator, session = await awaiting_approval(llm())
    await orchestrator.handle_command(
        session,
        AddSubtask(
            query="user added query", search_mode=SearchMode.NEWS, research_question_ids=["RQ2"]
        ),
    )
    assert session.plan is not None
    added = [t for t in session.plan.subtasks if t.origin == Origin.USER]
    assert [t.type for t in added] == [
        SubTaskType.SEARCH,
        SubTaskType.SUMMARIZE,
        SubTaskType.CROSS_CHECK,
    ]
    with pytest.raises(CommandRejected, match="unknown research question"):
        await orchestrator.handle_command(
            session, AddSubtask(query="another query", research_question_ids=["RQ9"])
        )


async def test_add_search_respects_the_search_budget() -> None:
    orchestrator, session = await awaiting_approval(llm())
    session.budget.searches = orchestrator.deps.blueprint.limits.max_searches - 2  # 2 pending
    with pytest.raises(CommandRejected, match="search budget"):
        await orchestrator.handle_command(session, AddSubtask(query="one more search"))


async def test_plan_changes_rejected_while_answering_questions() -> None:
    orchestrator, session = await awaiting_approval(llm())
    session.status = Status.AWAITING_ANSWERS
    with pytest.raises(CommandRejected, match="can't be changed"):
        await orchestrator.handle_command(session, SkipSubtask(subtask_id="t1"))


# --- Source overrides --------------------------------------------------------------------------


async def test_excluding_a_cited_source_reopens_and_rewrites_the_report() -> None:
    fake = llm(synth=2, gaps=2)
    fake.set("synthesize", synthesis_citing(["S1", "S3"]), synthesis_citing(["S3"]))
    orchestrator, session = await finished(fake)
    assert session.report is not None

    await orchestrator.handle_command(
        session, ExcludeSource(source_id="S1", reason="publisher has a conflict of interest")
    )
    assert session.status == Status.EXECUTING  # reopened
    source = session.get_source("S1")
    assert source is not None and source.exclusion is not None
    assert source.exclusion.stage == ExclusionStage.USER

    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE
    second_report_prompt = fake.calls_for("synthesize")[1].messages[0].content
    assert '<source id="S1"' not in second_report_prompt
    assert '<source id="S3"' in second_report_prompt
    assert len(fake.calls_for("gap_check")) == 2  # coverage re-checked


async def test_reincluding_a_source_summarizes_it_first() -> None:
    fake = llm(synth=2, gaps=2)
    fake.set("relevance", judge_all(low={"S3"}), judge_all(low={"S3"}))
    orchestrator, session = await finished(fake)
    assert session.get_source("S3").status == SourceStatus.EXCLUDED  # type: ignore[union-attr]
    assert "S3" not in {s.source_id for s in session.summaries}

    await orchestrator.handle_command(session, IncludeSource(source_id="S3"))
    assert session.plan is not None
    restore_task = session.plan.subtasks[-1]
    assert restore_task.origin == Origin.USER and restore_task.type == SubTaskType.SUMMARIZE
    await orchestrator.run_until_blocked(session)
    assert "S3" in {s.source_id for s in session.summaries}
    assert session.status == Status.DONE


async def test_exclude_twice_is_rejected() -> None:
    orchestrator, session = await finished(llm())
    session.status = Status.EXECUTING  # avoid the reopen path for this check
    await orchestrator.handle_command(session, ExcludeSource(source_id="S1"))
    with pytest.raises(CommandRejected, match="already excluded"):
        await orchestrator.handle_command(session, ExcludeSource(source_id="S1"))
    with pytest.raises(CommandRejected, match="no source S99"):
        await orchestrator.handle_command(session, IncludeSource(source_id="S99"))


async def test_tightening_the_window_excludes_older_sources() -> None:
    fake = llm(synth=2, gaps=2)
    orchestrator, session = await finished(fake)
    # Today is 2026-10-20: S3 (2026-02-01) is inside 365 days but outside 180.
    await orchestrator.handle_command(session, SetRecency(recency_days=180))
    s3 = session.get_source("S3")
    assert s3 is not None and s3.status == SourceStatus.EXCLUDED
    assert s3.exclusion is not None and s3.exclusion.rule == "recency"
    assert "window changed by the user" in s3.exclusion.reason
    assert session.status == Status.EXECUTING  # report will be rewritten
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE


async def test_widening_the_window_restores_date_excluded_sources() -> None:
    fake = llm(synth=2, gaps=2)
    orchestrator, session = await finished(fake)
    old = session.get_source("S2")  # 2025-03-01: excluded by the 365-day rule
    assert old is not None and old.exclusion is not None and old.exclusion.rule == "recency"

    await orchestrator.handle_command(session, SetRecency(recency_days=730))
    assert old.status == SourceStatus.KEPT
    assert old.relevance_reason is not None and "not relevance-checked" in old.relevance_reason
    await orchestrator.run_until_blocked(session)
    assert "S2" in {s.source_id for s in session.summaries}


async def test_window_change_that_changes_nothing_does_not_reopen() -> None:
    orchestrator, session = await finished(llm())
    await orchestrator.handle_command(session, SetRecency(recency_days=400))
    assert session.status == Status.DONE
    with pytest.raises(CommandRejected, match="already 400"):
        await orchestrator.handle_command(session, SetRecency(recency_days=400))


# --- Mode --------------------------------------------------------------------------------------


async def test_switching_to_autonomous_approves_a_waiting_plan() -> None:
    orchestrator, session = await awaiting_approval(llm())
    await orchestrator.handle_command(session, SetMode(mode=Mode.AUTONOMOUS))
    assert session.status == Status.EXECUTING
    assert any(e.action == "approved the plan automatically" for e in session.log)


async def test_switching_to_autonomous_skips_waiting_questions() -> None:
    from app.orchestrator.steps.clarify import ClarifyOutput
    from tests.helpers import question

    fake = llm()
    fake.set("clarify", ClarifyOutput(is_ambiguous=True, reasoning="r", questions=[question()]))
    orchestrator = Orchestrator(make_deps(fake, search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    assert session.status == Status.AWAITING_ANSWERS
    await orchestrator.handle_command(session, SetMode(mode=Mode.AUTONOMOUS))
    assert session.status == Status.PLANNING
    assert session.assumptions == ["Global coverage"]
    with pytest.raises(CommandRejected):
        await orchestrator.handle_command(session, AnswerQuestions(answers={}))


# --- State machine -----------------------------------------------------------------------------


def test_done_reopens_but_failed_stays_final() -> None:
    from app.orchestrator.state_machine import InvalidTransition

    assert next_status(Status.DONE, EventType.PLAN_CHANGED, Mode.SUPERVISED) == Status.EXECUTING
    with pytest.raises(InvalidTransition):
        next_status(Status.FAILED, EventType.PLAN_CHANGED, Mode.SUPERVISED)
