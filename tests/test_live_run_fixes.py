"""Fixes from the first live web run (Stack Overflow topic, 2026-10-22).

1. The user asked for "since ChatGPT launch (Nov 2022)" but the 365-day window excluded 17 key
   older sources. The planner may now widen the window (never narrow it), logged with a reason.
2. Contradiction lines in the Markdown report ended in "..".
3. The web server now writes finished sessions and reports to disk.
"""

import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.exports import export_session
from app.llm.fake import FakeLLM
from app.models import Actor, Contradiction, Report, Status
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.steps.plan import PlanOutput
from app.report_render import report_to_markdown
from app.search.fake import FakeSearch
from app.wiring import Wiring
from tests.helpers import (
    CLEAR_TOPIC,
    NO_CONTRADICTIONS,
    SUFFICIENT,
    TODAY,
    judge_all,
    make_deps,
    make_session,
    result,
    simple_plan,
    summary_for_prompt,
    synthesis_citing,
)


def plan_with_window(days: int | None, reason: str = "") -> PlanOutput:
    plan = simple_plan()
    plan.recency_days = days
    plan.recency_reason = reason
    return plan


def llm_for(plan: PlanOutput, *extra_plans: PlanOutput) -> FakeLLM:
    fake = FakeLLM()
    fake.add("clarify", CLEAR_TOPIC)
    fake.add("plan", plan, *extra_plans)
    fake.add("relevance", judge_all(), judge_all())
    fake.add("summarize", *[summary_for_prompt] * 4)
    fake.add("cross_check", NO_CONTRADICTIONS)
    fake.add("gap_check", SUFFICIENT)
    fake.add("synthesize", synthesis_citing(["S1"]))
    return fake


OLD_STUDY = {
    "AI newsroom adoption": [result("https://a.com/2023-study", published=date(2023, 6, 1))]
}


# --- 1. Planner widens the date window -------------------------------------------------------


async def test_planner_widens_the_window_and_old_sources_are_kept() -> None:
    reason = "The user asked for evidence since ChatGPT launched in Nov 2022."
    fake = llm_for(plan_with_window(1450, reason))
    session = await Orchestrator(make_deps(fake, FakeSearch(results=OLD_STUDY))).run_until_blocked(
        make_session()
    )
    assert session.settings.recency_days == 1450
    widened = [e for e in session.log if e.action.startswith("widened the date window")]
    assert widened and widened[0].actor == Actor.AGENT and widened[0].reason == reason
    assert session.get_source("S1").status.value == "kept"  # type: ignore[union-attr]


async def test_planner_never_narrows_the_users_window() -> None:
    fake = llm_for(plan_with_window(90, "only recent news"))
    session = await Orchestrator(make_deps(fake, FakeSearch())).run_until_blocked(make_session())
    assert session.settings.recency_days == 365
    assert not any("widened" in e.action for e in session.log)


async def test_widening_without_a_reason_is_sent_back() -> None:
    fake = llm_for(plan_with_window(1450, ""), plan_with_window(1450, "Covers 2022 onwards."))
    session = await Orchestrator(make_deps(fake, FakeSearch())).run_until_blocked(make_session())
    assert "recency_reason must explain" in fake.calls_for("plan")[1].messages[-1].content
    assert session.settings.recency_days == 1450


async def test_out_of_range_window_is_sent_back() -> None:
    fake = llm_for(plan_with_window(99999, "forever"), plan_with_window(None))
    session = await Orchestrator(make_deps(fake, FakeSearch())).run_until_blocked(make_session())
    assert "between 1 and 3650" in fake.calls_for("plan")[1].messages[-1].content
    assert session.settings.recency_days == 365


# --- 2. Report rendering ---------------------------------------------------------------------


def test_contradiction_line_has_no_double_period() -> None:
    session = make_session()
    session.status = Status.DONE
    session.report = Report(
        title="t",
        executive_summary="s",
        key_takeaways=[],
        sections=[],
        contradictions=[
            Contradiction(
                id="C1",
                topic="counts",
                claim_a="There were 300 questions.",
                source_a="S1",
                claim_b="There were 3,862 questions.",
                source_b="S2",
                explanation="They differ.",
            )
        ],
    )
    markdown = report_to_markdown(session)
    assert ".." not in markdown
    assert "[S1] says There were 300 questions; [S2] says There were 3,862 questions." in markdown


# --- 3. Exports ------------------------------------------------------------------------------


def test_export_session_writes_json_and_markdown(tmp_path: Path) -> None:
    session = make_session()
    session_path, report_path = export_session(session, tmp_path)
    assert session_path == tmp_path / "sessions" / f"{session.id}.json"
    assert report_path.read_text(encoding="utf-8").startswith(f"# {session.topic}")


async def _noop() -> None:
    return None


@pytest.fixture
def exporting_client(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    deps = make_deps(OfflineLLM(delay_s=0), OfflineSearch(today=TODAY, delay_s=0))
    app = create_app(Wiring(deps=deps, offline=True, close=_noop), export_dir=tmp_path)
    with TestClient(app) as client:
        yield client, tmp_path


def test_web_server_writes_finished_reports_to_disk(
    exporting_client: tuple[TestClient, Path],
) -> None:
    client, export_dir = exporting_client
    created = client.post("/api/sessions", json={"topic": "heat pumps", "mode": "autonomous"})
    session_id = created.json()["id"]
    report_path = export_dir / "reports" / f"{session_id}.md"
    for _ in range(300):
        if report_path.exists():
            break
        time.sleep(0.01)
    assert report_path.exists()
    assert (export_dir / "sessions" / f"{session_id}.json").exists()
    assert "## Key takeaways" in report_path.read_text(encoding="utf-8")
