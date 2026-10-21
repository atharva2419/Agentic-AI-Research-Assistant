"""The summary budget is shared fairly across summarize tasks and searches.

Regression test for a real run: with first-come-first-served selection, the first summarize task
took 10 of 15 slots and the last research questions lost their best sources (relevance 0.9).
"""

from app.models import ResearchSession, Source, SourceSummary, SubTaskStatus
from app.orchestrator.steps.plan import PlannedQuestion, PlanOutput, to_research_plan
from app.orchestrator.steps.summarize import fair_quota, sources_to_summarize
from tests.helpers import make_session, search_task, summarize_task


def two_group_session(per_search: dict[str, list[float]]) -> ResearchSession:
    """Searches t1-t4 summarized by s1, t5-t7 by s2 (the shape of the real run)."""
    plan = PlanOutput(
        objective="o",
        research_questions=[PlannedQuestion(id="RQ1", text="q")],
        subtasks=[
            *[search_task(f"t{i}", f"q{i}", ["RQ1"]) for i in range(1, 8)],
            summarize_task("s1", ["t1", "t2", "t3", "t4"]),
            summarize_task("s2", ["t5", "t6", "t7"]),
        ],
        rationale="r",
    )
    session = make_session()
    session.plan = to_research_plan(plan)
    for search_id, scores in per_search.items():
        for score in scores:
            n = len(session.sources) + 1
            session.sources.append(
                Source(
                    id=f"S{n}",
                    url=f"https://site{n}.com",
                    title=f"S{n}",
                    domain=f"site{n}.com",
                    found_by=[search_id],
                    relevance_score=score,
                )
            )
    return session


def mark_summarized(session: ResearchSession, sources: list[Source]) -> None:
    for s in sources:
        session.summaries.append(SourceSummary(source_id=s.id, summary="x", key_takeaways=[]))


REAL_RUN = {
    "t1": [0.85],
    "t2": [0.9, 0.7, 0.6],
    "t3": [0.85, 0.8, 0.8, 0.6],
    "t4": [0.85, 0.7],
    "t5": [0.7, 0.6],
    "t6": [0.9, 0.8, 0.7, 0.6, 0.6],
    "t7": [0.9, 0.8, 0.6],
}


def test_budget_is_split_in_proportion_to_searches() -> None:
    session = two_group_session(REAL_RUN)
    assert session.plan is not None
    first, second = session.plan.get_subtask("s1"), session.plan.get_subtask("s2")
    assert first is not None and second is not None
    assert fair_quota(session, first, remaining=15) == 8  # 15 * 4/7

    chosen, skipped = sources_to_summarize(session, first, max_total=15)
    assert len(chosen) == 8 and len(skipped) == 2
    first.status = SubTaskStatus.DONE
    mark_summarized(session, chosen)

    chosen2, _ = sources_to_summarize(session, second, max_total=15)
    assert len(chosen2) == 7  # the last task gets everything left


def test_every_search_gets_its_best_source_first() -> None:
    session = two_group_session(REAL_RUN)
    assert session.plan is not None
    second = session.plan.get_subtask("s2")
    assert second is not None
    session.plan.subtasks[7].status = SubTaskStatus.DONE  # s1 already ran
    chosen, _ = sources_to_summarize(session, second, max_total=3)
    by_id = {s.id: s for s in session.sources}
    picked = {(by_id[s.id].found_by[0], s.relevance_score) for s in chosen}
    assert picked == {("t5", 0.7), ("t6", 0.9), ("t7", 0.9)}


def test_when_quota_ends_mid_round_the_weaker_offer_loses() -> None:
    session = two_group_session({"t1": [0.9, 0.6], "t2": [0.9, 0.8]})
    assert session.plan is not None
    first = session.plan.get_subtask("s1")
    assert first is not None
    session.plan.subtasks[8].status = SubTaskStatus.DONE  # s2 not waiting
    chosen, skipped = sources_to_summarize(session, first, max_total=3)
    assert sorted(s.relevance_score or 0 for s in chosen) == [0.8, 0.9, 0.9]
    assert [s.relevance_score for s in skipped] == [0.6]


def test_unused_share_rolls_over_to_later_tasks() -> None:
    session = two_group_session({"t1": [0.9], "t5": [0.9] * 12})
    assert session.plan is not None
    first, second = session.plan.get_subtask("s1"), session.plan.get_subtask("s2")
    assert first is not None and second is not None
    chosen, skipped = sources_to_summarize(session, first, max_total=15)
    assert len(chosen) == 1 and skipped == []
    first.status = SubTaskStatus.DONE
    mark_summarized(session, chosen)

    chosen2, _ = sources_to_summarize(session, second, max_total=15)
    assert len(chosen2) == 12  # 14 slots left, only 12 candidates


def test_source_found_by_two_searches_is_picked_once() -> None:
    session = two_group_session({"t1": [0.9], "t2": [0.5]})
    session.sources[0].found_by = ["t1", "t2"]
    assert session.plan is not None
    first = session.plan.get_subtask("s1")
    assert first is not None
    session.plan.subtasks[8].status = SubTaskStatus.DONE  # s2 not waiting
    chosen, skipped = sources_to_summarize(session, first, max_total=15)
    assert [s.id for s in chosen] == ["S1", "S2"]
    assert skipped == []
