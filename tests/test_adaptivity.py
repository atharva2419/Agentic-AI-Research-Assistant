"""Phase 4: clarifying questions, the gap check (replan / ask the user) and budgets."""

import pytest

from app.llm.fake import FakeLLM
from app.models import (
    AnswerQuestions,
    ApprovePlan,
    Mode,
    Origin,
    SearchMode,
    Status,
    SubTaskStatus,
    SubTaskType,
)
from app.orchestrator.budget import skip_searches_over_cost_cap
from app.orchestrator.errors import CommandRejected
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.steps.clarify import ClarifyOutput
from app.orchestrator.steps.cross_check import ContradictionOutput, CrossCheckOutput
from app.orchestrator.steps.gap_check import (
    GapCheckOutput,
    GapOutput,
    NewSearchOutput,
    gap_options,
)
from app.orchestrator.steps.plan import to_research_plan
from app.search.fake import FakeSearch
from tests.helpers import (
    CLEAR_TOPIC,
    NO_CONTRADICTIONS,
    SUFFICIENT,
    judge_all,
    make_deps,
    make_session,
    question,
    result,
    simple_plan,
    summary_for_prompt,
    synthesis_citing,
)

SEARCHES = {
    "AI newsroom adoption": [result("https://a.com/adoption")],
    "AI journalism jobs": [result("https://b.com/jobs")],
    "AI journalism layoffs 2026 data": [result("https://c.com/layoffs")],
}


def search() -> FakeSearch:
    return FakeSearch(results=SEARCHES)


def base_llm(clarify: ClarifyOutput = CLEAR_TOPIC) -> FakeLLM:
    """Responses for a run with no replan; tests override steps as needed."""
    llm = FakeLLM()
    llm.add("clarify", clarify)
    llm.add("plan", simple_plan())
    llm.add("relevance", judge_all(), judge_all(), judge_all())
    llm.add("summarize", *[summary_for_prompt] * 3)
    llm.add("cross_check", NO_CONTRADICTIONS, NO_CONTRADICTIONS)
    llm.add("gap_check", SUFFICIENT)
    llm.add("synthesize", synthesis_citing(["S1", "S2"]))
    return llm


AMBIGUOUS = ClarifyOutput(
    is_ambiguous=True,
    reasoning="Region and angle change the research a lot.",
    questions=[question("Which region?", "Global"), question("Which angle?", "Jobs and trust")],
)

REPLAN = GapCheckOutput(
    verdict="replan",
    reasoning="RQ2 has only one source.",
    gaps=[GapOutput(research_question_id="RQ2", description="only one source on jobs")],
    new_searches=[
        NewSearchOutput(
            query="AI journalism layoffs 2026 data",
            search_mode=SearchMode.GENERAL,
            research_question_ids=["RQ2"],
            reason="Find data on job impact",
        )
    ],
    question=None,
)

NEEDS_USER = GapCheckOutput(
    verdict="needs_user",
    reasoning="Sources split between print and broadcast.",
    gaps=[],
    new_searches=[],
    question=question("Print or broadcast?", "Both, weighted to print"),
)


# --- Clarifying questions ----------------------------------------------------------------------


async def test_supervised_session_waits_for_answers_and_uses_them() -> None:
    llm = base_llm(clarify=AMBIGUOUS)
    orchestrator = Orchestrator(make_deps(llm, search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    assert session.status == Status.AWAITING_ANSWERS
    assert [q.id for q in session.pending_questions()] == ["q1", "q2"]

    await orchestrator.handle_command(
        session, AnswerQuestions(answers={"q1": "United States", "q2": None})
    )
    assert session.status == Status.PLANNING
    assert session.assumptions == ["Jobs and trust"]

    await orchestrator.run_until_blocked(session)
    plan_prompt = llm.calls_for("plan")[0].messages[0].content
    assert "A: United States" in plan_prompt
    assert "Jobs and trust" in plan_prompt


async def test_question_left_out_of_answers_counts_as_skipped() -> None:
    orchestrator = Orchestrator(make_deps(base_llm(clarify=AMBIGUOUS), search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    await orchestrator.handle_command(session, AnswerQuestions(answers={"q1": "EU"}))
    assert session.questions[1].skipped
    assert session.assumptions == ["Jobs and trust"]


async def test_autonomous_mode_does_not_wait_and_states_assumptions() -> None:
    llm = base_llm(clarify=AMBIGUOUS)
    session = await Orchestrator(make_deps(llm, search())).run_until_blocked(make_session())
    assert session.status == Status.DONE
    assert session.assumptions == ["Global", "Jobs and trust"]
    assert any("autonomous mode" in e.action for e in session.log)
    assert session.report is not None
    assert session.report.assumptions == ["Global", "Jobs and trust"]


async def test_inconsistent_clarify_output_is_corrected() -> None:
    contradictory = ClarifyOutput(is_ambiguous=True, reasoning="?", questions=[])
    llm = base_llm()
    llm.set("clarify", contradictory, CLEAR_TOPIC)
    session = await Orchestrator(make_deps(llm, search())).run_until_blocked(make_session())
    assert session.status == Status.DONE
    assert "no questions were asked" in llm.calls_for("clarify")[1].messages[-1].content


async def test_answers_rejected_when_nothing_is_asked() -> None:
    orchestrator = Orchestrator(make_deps(FakeLLM(), search()))
    with pytest.raises(CommandRejected):
        await orchestrator.handle_command(make_session(), AnswerQuestions(answers={}))


async def test_unknown_question_id_rejected() -> None:
    orchestrator = Orchestrator(make_deps(base_llm(clarify=AMBIGUOUS), search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    with pytest.raises(CommandRejected, match="q9"):
        await orchestrator.handle_command(session, AnswerQuestions(answers={"q9": "x"}))


# --- Gap check: replan -------------------------------------------------------------------------


async def test_replan_adds_searches_and_runs_them() -> None:
    llm = base_llm()
    llm.set("gap_check", REPLAN, SUFFICIENT)
    llm.set("synthesize", synthesis_citing(["S1", "S3"]))
    fake_search = search()
    session = await Orchestrator(make_deps(llm, fake_search)).run_until_blocked(make_session())

    assert session.status == Status.DONE
    assert session.plan is not None
    assert session.plan.version == 2
    assert session.budget.replans == 1
    new = [t for t in session.plan.subtasks if t.origin == Origin.REPLAN]
    assert [(t.id, t.type) for t in new] == [
        ("t5", SubTaskType.SEARCH),
        ("t6", SubTaskType.SUMMARIZE),
        ("t7", SubTaskType.CROSS_CHECK),
    ]
    assert new[2].depends_on == ["t6", "t3"]
    assert all(t.status == SubTaskStatus.DONE for t in session.plan.subtasks)
    assert fake_search.queries[-1].query == "AI journalism layoffs 2026 data"
    assert "S3" in {s.source_id for s in session.summaries}

    second_review = llm.calls_for("gap_check")[1].messages[0].content
    assert "AI journalism layoffs 2026 data" in second_review  # sees the new search


async def test_invalid_replan_is_sent_back() -> None:
    bad = REPLAN.model_copy(deep=True)
    bad.new_searches[0].research_question_ids = ["RQ9"]
    llm = base_llm()
    llm.set("gap_check", bad, SUFFICIENT)
    session = await Orchestrator(make_deps(llm, search())).run_until_blocked(make_session())
    assert session.status == Status.DONE
    assert "unknown research question 'RQ9'" in llm.calls_for("gap_check")[1].messages[-1].content
    assert session.budget.replans == 0


async def test_contradiction_found_twice_is_reported_once() -> None:
    same = CrossCheckOutput(
        contradictions=[
            ContradictionOutput(
                topic="jobs",
                claim_a="a",
                source_a="S1",
                claim_b="b",
                source_b="S2",
                explanation="e",
                likely_cause="c",
            )
        ]
    )
    llm = base_llm()
    llm.set("gap_check", REPLAN, SUFFICIENT)
    llm.set("cross_check", same, same)
    session = await Orchestrator(make_deps(llm, search())).run_until_blocked(make_session())
    assert [c.id for c in session.contradictions] == ["C1"]


async def test_autonomous_session_with_no_options_skips_the_review() -> None:
    llm = base_llm()
    llm.set("gap_check")  # must not be called
    deps = make_deps(llm, search())
    session = make_session()
    session.budget.replans = deps.blueprint.limits.max_replans
    session = await Orchestrator(deps).run_until_blocked(session)
    assert session.status == Status.DONE
    assert llm.calls_for("gap_check") == []
    assert any(e.action == "skipped coverage review" for e in session.log)


# --- Gap check: ask the user -------------------------------------------------------------------


async def test_gap_question_waits_then_rechecks_with_the_answer() -> None:
    llm = base_llm()
    llm.set("gap_check", NEEDS_USER, SUFFICIENT)
    orchestrator = Orchestrator(make_deps(llm, search()))
    session = make_session(Mode.SUPERVISED)
    await orchestrator.run_until_blocked(session)
    await orchestrator.handle_command(session, ApprovePlan())
    await orchestrator.run_until_blocked(session)

    assert session.status == Status.AWAITING_ANSWERS
    assert session.questions[-1].origin == "gap_check"
    await orchestrator.handle_command(
        session, AnswerQuestions(answers={session.questions[-1].id: "Print only"})
    )
    assert session.status == Status.GAP_CHECK  # re-checks; does not re-plan from scratch

    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE
    second_review = llm.calls_for("gap_check")[1].messages[0].content
    assert "A: Print only" in second_review
    assert "needs_user unavailable" in second_review  # asked once already


async def test_needs_user_is_rejected_in_autonomous_mode() -> None:
    llm = base_llm()
    llm.set("gap_check", NEEDS_USER, SUFFICIENT)
    session = await Orchestrator(make_deps(llm, search())).run_until_blocked(make_session())
    assert session.status == Status.DONE
    assert "not available now" in llm.calls_for("gap_check")[1].messages[-1].content
    assert session.questions == []


# --- Budgets -----------------------------------------------------------------------------------


def test_replans_stop_at_the_cost_ceiling() -> None:
    deps = make_deps(FakeLLM(), search())
    session = make_session(Mode.SUPERVISED)
    session.budget.cost_usd = deps.blueprint.limits.replan_cost_ceiling_usd
    options = gap_options(deps, session)
    assert not options.can_replan
    assert options.can_ask
    assert "replan ceiling" in options.notes[0]


def test_pending_searches_are_skipped_past_the_cost_cap() -> None:
    session = make_session()
    session.plan = to_research_plan(simple_plan())
    session.plan.subtasks[0].status = SubTaskStatus.DONE
    assert skip_searches_over_cost_cap(session, max_cost_usd=0.75) == []
    session.budget.cost_usd = 0.80
    skipped = skip_searches_over_cost_cap(session, max_cost_usd=0.75)
    assert [t.id for t in skipped] == ["t2"]
    assert session.plan.subtasks[2].status == SubTaskStatus.PENDING  # summaries still run


async def test_first_plan_leaves_the_summary_reserve_for_replans() -> None:
    llm = base_llm()
    llm.set("summarize", *[summary_for_prompt] * 2)
    llm.set("synthesize", synthesis_citing(["S1"]))
    deps = make_deps(llm, search())
    limits = deps.blueprint.limits.model_copy(
        update={"max_sources_summarized": 3, "summary_reserve_for_replans": 2}
    )
    deps.blueprint = deps.blueprint.model_copy(update={"limits": limits})
    session = await Orchestrator(deps).run_until_blocked(make_session())
    assert len(session.summaries) == 1  # 3 slots minus 2 reserved
    assert any("skipped 1 source" in e.action for e in session.log)
