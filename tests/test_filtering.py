from datetime import date

from app.filtering import RuleReport, apply_rules, domain_of, normalize_url, recency_problem
from app.models import Source, SourceStatus
from app.search.base import SearchResult
from tests.helpers import BLUEPRINT, TODAY, result

CONFIG = BLUEPRINT.filtering


def test_domain_of() -> None:
    assert domain_of("https://www.Example.com/a") == "example.com"


def test_normalize_url_ignores_noise() -> None:
    a = normalize_url("http://www.example.com/story/?utm_source=x&id=7#comments")
    b = normalize_url("https://example.com/story?id=7")
    assert a == b


def recency(published: date | None, days: int = 365, policy: str = "keep_flagged") -> str | None:
    return recency_problem(published, today=TODAY, recency_days=days, unknown_date_policy=policy)


def test_recency_window() -> None:
    assert recency(date(2026, 1, 1)) is None
    problem = recency(date(2024, 1, 1))
    assert problem is not None and "outdated" in problem


def test_unknown_date_policy() -> None:
    assert recency(None, policy="keep_flagged") is None
    assert recency(None, policy="exclude") == "publication date unknown"


def run(results: list[SearchResult], existing: list[Source] | None = None) -> RuleReport:
    return apply_rules(
        results, existing=existing or [], today=TODAY, recency_days=365, config=CONFIG
    )


def test_old_source_is_excluded_with_reason() -> None:
    report = run([result("https://a.com/old", published=date(2023, 2, 10))])
    reason = report.outcomes[0].exclusion_reason
    assert reason is not None and "2023-02-10" in reason


def test_duplicates_within_batch_and_session() -> None:
    known = Source(id="S1", url="https://a.com/x", title="x", domain="a.com")
    report = run(
        [result("https://www.a.com/x/"), result("https://b.com/y"), result("https://b.com/y")],
        existing=[known],
    )
    assert [o.result.url for o in report.outcomes] == ["https://b.com/y"]
    assert len(report.duplicates) == 2


def test_short_content_is_excluded() -> None:
    report = run([result("https://a.com/x", content="Too short.")])
    reason = report.outcomes[0].exclusion_reason
    assert reason is not None and "too little content" in reason


def test_domain_cap() -> None:
    report = run([result(f"https://a.com/{i}") for i in range(3)])
    reasons = [o.exclusion_reason for o in report.outcomes]
    assert reasons[:2] == [None, None]
    assert reasons[2] is not None and "capped" in reasons[2]


def test_domain_cap_counts_existing_kept_sources_only() -> None:
    existing = [
        Source(id="S1", url="https://a.com/1", title="1", domain="a.com"),
        Source(
            id="S2",
            url="https://a.com/2",
            title="2",
            domain="a.com",
            status=SourceStatus.EXCLUDED,
        ),
    ]
    report = run([result("https://a.com/3"), result("https://a.com/4")], existing=existing)
    reasons = [o.exclusion_reason for o in report.outcomes]
    assert reasons[0] is None
    assert reasons[1] is not None
