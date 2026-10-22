"""Optional priority keywords: guidance for every prompt, measured coverage, never a filter."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.keywords import keyword_coverage, normalize_keywords
from app.models import Source, SourceStatus
from app.orchestrator.orchestrator import Orchestrator
from app.report_render import report_to_markdown
from app.wiring import Wiring
from tests.helpers import TODAY, make_deps, make_session
from tests.test_orchestrator import fixture_search, scripted_llm


def test_normalize_keywords() -> None:
    raw = ["  GA4 ", "hreflang", "", "ga4", "headless   CMS"]
    assert normalize_keywords(raw) == ["GA4", "hreflang", "headless CMS"]


def test_coverage_counts_kept_sources_only() -> None:
    sources = [
        Source(id="S1", url="u", title="GA4 setup", domain="a.com"),
        Source(id="S2", url="u", title="t", domain="b.com", content="...hreflang tags..."),
        Source(id="S3", url="u", title="GA4 again", domain="c.com", status=SourceStatus.EXCLUDED),
    ]
    assert keyword_coverage(["ga4", "hreflang", "AMP"], sources) == {
        "ga4": ["S1"],
        "hreflang": ["S2"],
        "AMP": [],
    }


async def test_keywords_reach_the_prompts_and_the_report() -> None:
    llm = scripted_llm()
    session = make_session()
    session.settings.keywords = ["newsrooms", "blockchain"]
    session = await Orchestrator(make_deps(llm, fixture_search())).run_until_blocked(session)

    plan_prompt = llm.calls_for("plan")[0].messages[0].content
    assert "Priority keywords from the user: newsrooms, blockchain" in plan_prompt
    gap_prompt = llm.calls_for("gap_check")[0].messages[0].content
    assert "- blockchain: 0 source(s)" in gap_prompt  # an uncovered keyword is visible
    assert session.report is not None
    assert session.report.keyword_coverage["blockchain"] == []
    assert session.report.keyword_coverage["newsrooms"]  # fixture pages mention newsrooms
    assert "## Priority keyword coverage" in report_to_markdown(session)


async def test_sources_are_never_excluded_for_missing_a_keyword() -> None:
    session = make_session()
    session.settings.keywords = ["nothing-mentions-this"]
    session = await Orchestrator(make_deps(scripted_llm(), fixture_search())).run_until_blocked(
        session
    )
    assert [s.id for s in session.kept_sources()] == ["S1", "S3"]  # same as without keywords


async def _noop() -> None:
    return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    deps = make_deps(OfflineLLM(delay_s=0), OfflineSearch(today=TODAY, delay_s=0))
    with TestClient(create_app(Wiring(deps=deps, offline=True, close=_noop))) as test_client:
        yield test_client


def test_api_accepts_and_cleans_keywords(client: TestClient) -> None:
    body = {"topic": "website migration", "keywords": [" GA4", "ga4", "hreflang "]}
    session = client.post("/api/sessions", json=body).json()
    assert session["settings"]["keywords"] == ["GA4", "hreflang"]


def test_api_rejects_too_many_or_too_long_keywords(client: TestClient) -> None:
    too_many = {"topic": "website migration", "keywords": [f"k{i}" for i in range(9)]}
    assert client.post("/api/sessions", json=too_many).status_code == 422
    too_long = {"topic": "website migration", "keywords": ["x" * 41]}
    assert client.post("/api/sessions", json=too_long).status_code == 422
