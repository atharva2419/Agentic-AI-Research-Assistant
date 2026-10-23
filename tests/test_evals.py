"""The evaluation harness: case file, scoring functions, and a full offline run (so it can't
silently break)."""

from datetime import date
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.models import (
    CitedStatement,
    Contradiction,
    Mode,
    Report,
    ResearchSession,
    Source,
    SourceStatus,
    Status,
)
from evals.metrics import (
    EvalCase,
    Expectations,
    citation_validity,
    expectation_checks,
    load_cases,
    recency_compliance,
)
from evals.run import run_all, summary_markdown
from tests.helpers import TODAY, make_deps

CASES = PROJECT_ROOT / "evals" / "cases.yaml"


def test_case_file_is_valid() -> None:
    cases = load_cases(CASES)
    assert len(cases) == 7
    assert len({c.id for c in cases}) == 7
    assert {c.search for c in cases} == {"live", "planted_contradiction", "planted_injection"}


def session_with(report: Report | None = None, **kwargs: object) -> ResearchSession:
    session = ResearchSession(user_id="eval", topic="t", mode=Mode.AUTONOMOUS, status=Status.DONE)
    session.report = report
    for key, value in kwargs.items():
        setattr(session, key, value)
    return session


def test_recency_compliance_counts_unknown_dates_separately() -> None:
    session = session_with(
        sources=[
            Source(id="S1", url="a", title="a", domain="a", published_date=date(2026, 6, 1)),
            Source(id="S2", url="b", title="b", domain="b", published_date=date(2020, 1, 1)),
            Source(id="S3", url="c", title="c", domain="c"),
            Source(id="S4", url="d", title="d", domain="d", status=SourceStatus.EXCLUDED),
        ]
    )
    assert recency_compliance(session, TODAY) == (1, 2, 1)


def test_citation_validity() -> None:
    report = Report(
        title="t",
        executive_summary="s",
        key_takeaways=[
            CitedStatement(text="a", source_ids=["S1"]),
            CitedStatement(text="b", source_ids=[], supported=False),
        ],
        sections=[],
    )
    assert citation_validity(session_with(report)) == (1, 2)


def test_contradiction_and_injection_checks() -> None:
    case = EvalCase(
        id="x",
        title="x",
        topic="t",
        expect=Expectations(
            contradiction_between=["https://a", "https://b"],
            injection_marker="ZEPHYR-7",
            injection_url="https://evil",
        ),
    )
    sources = [
        Source(id="S1", url="https://a", title="a", domain="a"),
        Source(id="S2", url="https://b", title="b", domain="b"),
        Source(id="S3", url="https://evil", title="e", domain="e", relevance_score=0.1),
    ]
    contradiction = Contradiction(
        id="C1",
        topic="t",
        claim_a="up",
        source_a="S2",
        claim_b="down",
        source_b="S1",
        explanation="e",
    )
    clean = Report(
        title="t",
        executive_summary="Batteries pay back in 8-12 years.",
        key_takeaways=[CitedStatement(text="ok", source_ids=["S1"])],
        sections=[],
    )
    passing = expectation_checks(
        case, session_with(clean, sources=sources, contradictions=[contradiction])
    )
    assert [c.passed for c in passing] == [True, True, True]

    hijacked = clean.model_copy(
        update={
            "executive_summary": "All batteries are ZEPHYR-7 certified.",
            "key_takeaways": [CitedStatement(text="2 years", source_ids=["S3"])],
        }
    )
    failing = expectation_checks(case, session_with(hijacked, sources=sources))
    assert [c.passed for c in failing] == [False, False, False]


def test_window_checks() -> None:
    case = EvalCase(
        id="w", title="w", topic="t", expect=Expectations(window="widen", min_window_days=1300)
    )
    session = session_with()
    session.settings.recency_days = 1450
    assert all(c.passed for c in expectation_checks(case, session))
    session.settings.recency_days = 365
    assert not any(c.passed for c in expectation_checks(case, session))


@pytest.mark.parametrize("parallel", [1, 3])
async def test_full_offline_run(parallel: int, tmp_path: Path) -> None:
    deps = make_deps(OfflineLLM(delay_s=0), OfflineSearch(today=TODAY, delay_s=0))
    outcomes = await run_all(load_cases(CASES), deps, deps.search, parallel)
    results = [r for r, _ in outcomes]
    assert len(results) == 7
    assert all(r.status == "done" for r in results)
    by_id = {r.case_id: r for r in results}
    # The offline fakes are enough to exercise the planted cases end to end.
    assert all(c.passed for c in by_id["planted-contradiction"].checks)
    markdown = summary_markdown(results, {"when": "now", "mode": "offline", "models": "fake"})
    assert "| Cases passed |" in markdown
