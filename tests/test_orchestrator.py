"""Whole sessions driven through the orchestrator with FakeLLM and FakeSearch."""

from datetime import date

import pytest

from app.llm.base import LLMError, LLMRequest
from app.llm.fake import FakeLLM
from app.models import (
    Actor,
    ApprovePlan,
    ExclusionStage,
    Mode,
    Pause,
    Resume,
    SourceStatus,
    Status,
    SubTaskStatus,
)
from app.orchestrator.orchestrator import CommandRejected, Orchestrator
from app.orchestrator.steps.cross_check import ContradictionOutput, CrossCheckOutput
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


def fixture_search(**kwargs: object) -> FakeSearch:
    return FakeSearch(
        results={
            "AI newsroom adoption": [
                result("https://a.com/adoption"),
                result("https://old.com/2019", published=date(2019, 1, 1)),
            ],
            "AI journalism jobs": [
                result("https://b.com/jobs"),
                result("https://a.com/adoption?utm_source=x"),  # duplicate of S1
                result("https://spam.com/x"),
            ],
        },
        **kwargs,  # type: ignore[arg-type]
    )


def scripted_llm() -> FakeLLM:
    llm = FakeLLM()
    llm.add("clarify", CLEAR_TOPIC)
    llm.add("plan", simple_plan())
    llm.add("gap_check", SUFFICIENT)
    llm.add("relevance", judge_all(low={"S4"}), judge_all(low={"S4"}))
    llm.add("summarize", summary_for_prompt, summary_for_prompt)
    llm.add("cross_check", NO_CONTRADICTIONS)
    llm.add("synthesize", synthesis_citing(["S1", "S3"]))
    return llm


async def test_autonomous_session_runs_start_to_finish() -> None:
    llm, search = scripted_llm(), fixture_search()
    orchestrator = Orchestrator(make_deps(llm, search))
    session = await orchestrator.run_until_blocked(make_session(Mode.AUTONOMOUS))

    assert session.status == Status.DONE
    assert session.plan is not None
    assert all(t.status == SubTaskStatus.DONE for t in session.plan.subtasks)
    assert [q.query for q in search.queries] == ["AI newsroom adoption", "AI journalism jobs"]

    by_id = {s.id: s for s in session.sources}
    assert set(by_id) == {"S1", "S2", "S3", "S4"}  # the duplicate was not added again
    assert by_id["S1"].found_by == ["t1", "t2"]
    assert by_id["S2"].exclusion is not None
    assert by_id["S2"].exclusion.stage == ExclusionStage.RULE  # 2019: outdated
    assert by_id["S4"].exclusion is not None
    assert by_id["S4"].exclusion.stage == ExclusionStage.RELEVANCE
    assert [s.id for s in session.kept_sources()] == ["S1", "S3"]

    assert [s.source_id for s in session.summaries] == ["S1", "S3"]
    assert all(len(s.quotes) == 1 for s in session.summaries)  # made-up quote removed

    assert session.report is not None
    assert all(s.supported for s in session.report.key_takeaways)
    assert session.budget.searches == 2
    # clarify, plan, 2 relevance, 2 summaries, cross-check, gap check, synthesize
    assert session.budget.llm_calls == 9
    assert session.budget.cost_usd > 0


async def test_every_log_entry_has_increasing_seq() -> None:
    orchestrator = Orchestrator(make_deps(scripted_llm(), fixture_search()))
    session = await orchestrator.run_until_blocked(make_session())
    assert [e.seq for e in session.log] == list(range(1, len(session.log) + 1))
    assert any(e.step == "filter" and "outdated" in e.reason for e in session.log)


async def test_supervised_session_waits_for_plan_approval() -> None:
    orchestrator = Orchestrator(make_deps(scripted_llm(), fixture_search()))
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    assert session.status == Status.AWAITING_PLAN_APPROVAL
    assert session.sources == []

    await orchestrator.step(session)  # waiting: nothing happens
    assert session.status == Status.AWAITING_PLAN_APPROVAL

    await orchestrator.handle_command(session, ApprovePlan())
    assert session.log[-2].actor == Actor.USER
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE


async def test_approve_is_rejected_when_no_plan_is_waiting() -> None:
    orchestrator = Orchestrator(make_deps(FakeLLM(), FakeSearch()))
    with pytest.raises(CommandRejected):
        await orchestrator.handle_command(make_session(), ApprovePlan())


async def test_pause_stops_work_and_resume_continues() -> None:
    orchestrator = Orchestrator(make_deps(scripted_llm(), fixture_search()))
    session = make_session()
    await orchestrator.step(session)  # CREATED -> CLARIFYING
    await orchestrator.handle_command(session, Pause())
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.CLARIFYING

    await orchestrator.handle_command(session, Resume())
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE


async def test_invalid_plan_is_sent_back_and_corrected() -> None:
    bad = simple_plan()
    bad.subtasks[2].depends_on = ["t1"]  # t2 is never summarized
    llm = scripted_llm()
    llm.set("plan", bad, simple_plan())
    orchestrator = Orchestrator(make_deps(llm, fixture_search()))
    session = await orchestrator.run_until_blocked(make_session())

    assert session.status == Status.DONE
    assert len(llm.calls_for("plan")) == 2
    assert "'t2' is not summarized" in llm.calls_for("plan")[1].messages[-1].content
    assert any(e.action == "LLM output corrected" for e in session.log)


async def test_failed_search_does_not_stop_the_session() -> None:
    llm = scripted_llm()
    llm.set("relevance", judge_all(low={"S4"}))
    llm.set("synthesize", synthesis_citing(["S1"]))
    llm.set("summarize", summary_for_prompt)
    search = fixture_search(failing_queries={"AI journalism jobs"})
    session = await Orchestrator(make_deps(llm, search)).run_until_blocked(make_session())

    assert session.status == Status.DONE
    assert session.plan is not None
    assert session.plan.subtasks[1].status == SubTaskStatus.FAILED
    assert session.plan.subtasks[3].note is not None
    assert "fewer than 2" in session.plan.subtasks[3].note


async def test_unknown_citations_are_flagged_not_dropped() -> None:
    llm = scripted_llm()
    bad = synthesis_citing(["S1", "S77"])
    llm.set("synthesize", bad, bad, bad)
    session = await Orchestrator(make_deps(llm, fixture_search())).run_until_blocked(make_session())
    assert session.status == Status.DONE
    assert session.report is not None
    takeaway = session.report.key_takeaways[0]
    assert takeaway.supported is False
    assert takeaway.source_ids == ["S1"]
    assert len(llm.calls_for("synthesize")) == 3


async def test_no_usable_sources_gives_an_honest_empty_report() -> None:
    llm = FakeLLM()
    llm.add("clarify", CLEAR_TOPIC)
    llm.add("plan", simple_plan())
    llm.add("gap_check", SUFFICIENT)
    search = FakeSearch(default=[result("https://old.com/a", published=date(2020, 1, 1))])
    session = await Orchestrator(make_deps(llm, search)).run_until_blocked(make_session())
    assert session.status == Status.DONE
    assert session.report is not None
    assert "No usable sources" in session.report.executive_summary
    assert llm.calls_for("synthesize") == []


async def test_contradictions_are_validated_and_reach_the_report() -> None:
    llm = scripted_llm()

    def contradiction(request: LLMRequest) -> CrossCheckOutput:
        return CrossCheckOutput(
            contradictions=[
                ContradictionOutput(
                    topic="job losses",
                    claim_a="20% fewer jobs",
                    source_a="S1",
                    claim_b="no change in jobs",
                    source_b="S3",
                    explanation="opposite conclusions",
                    likely_cause="different years",
                )
            ]
        )

    llm.set("cross_check", contradiction)
    session = await Orchestrator(make_deps(llm, fixture_search())).run_until_blocked(make_session())
    assert session.report is not None
    assert [c.id for c in session.report.contradictions] == ["C1"]
    assert "C1" in llm.calls_for("synthesize")[0].messages[0].content


async def test_llm_outage_fails_the_session_with_a_reason() -> None:
    class BrokenLLM(FakeLLM):
        async def complete(self, request: LLMRequest):  # type: ignore[no-untyped-def]
            raise LLMError("API error 529: overloaded")

    session = await Orchestrator(make_deps(BrokenLLM(), FakeSearch())).run_until_blocked(
        make_session()
    )
    assert session.status == Status.FAILED
    assert session.error is not None and "overloaded" in session.error


async def test_user_excluded_status_values_are_strings_in_json() -> None:
    session = await Orchestrator(make_deps(scripted_llm(), fixture_search())).run_until_blocked(
        make_session()
    )
    data = session.model_dump(mode="json")
    assert data["status"] == "done"
    assert data["sources"][1]["status"] == SourceStatus.EXCLUDED.value
