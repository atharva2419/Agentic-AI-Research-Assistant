"""The offline demo pair must drive a full session through every validator, for any topic."""

import pytest

from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.models import AnswerQuestions, ApprovePlan, ExclusionStage, Mode, Status
from app.orchestrator.orchestrator import Orchestrator
from tests.helpers import TODAY, make_deps, make_session


def offline_orchestrator() -> Orchestrator:
    return Orchestrator(make_deps(OfflineLLM(delay_s=0), OfflineSearch(today=TODAY, delay_s=0)))


@pytest.mark.parametrize("topic", ["AI in journalism", "heat pumps in cold climates"])
async def test_autonomous_offline_session_completes(topic: str) -> None:
    session = make_session(Mode.AUTONOMOUS)
    session.topic = topic
    session = await offline_orchestrator().run_until_blocked(session)

    assert session.status == Status.DONE, session.error
    assert session.assumptions  # the offline clarify question was auto-skipped
    stages = {s.exclusion.stage for s in session.sources if s.exclusion}
    assert stages == {ExclusionStage.RULE, ExclusionStage.RELEVANCE}  # archive + listicle
    assert session.contradictions
    report = session.report
    assert report is not None
    statements = [*report.key_takeaways, *(c for sec in report.sections for c in sec.statements)]
    assert all(st.supported for st in statements)
    assert all(len(summary.quotes) == 1 for summary in session.summaries)  # quotes verified


async def test_supervised_offline_session_waits_twice() -> None:
    orchestrator = offline_orchestrator()
    session = await orchestrator.run_until_blocked(make_session(Mode.SUPERVISED))
    assert session.status == Status.AWAITING_ANSWERS
    await orchestrator.handle_command(session, AnswerQuestions(answers={"q1": "European Union"}))
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.AWAITING_PLAN_APPROVAL
    await orchestrator.handle_command(session, ApprovePlan())
    await orchestrator.run_until_blocked(session)
    assert session.status == Status.DONE
