"""Code rules that filter search results before any LLM sees them.

Pure functions: `today` is passed in, so tests never depend on the real date. Every exclusion
comes with a human-readable reason that is shown to the user.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.blueprint import FilteringConfig
from app.models import ExclusionRule, Source, SourceStatus
from app.search.base import SearchResult

TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref")


def domain_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.").lower()


def normalize_url(url: str) -> str:
    """Canonical form for duplicate detection: lowercase host, no www, no tracking params,
    no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(TRACKING_PARAMS)]
    )
    path = parts.path.rstrip("/")
    return urlunsplit(("https", domain_of(url), path, query, ""))


def recency_problem(
    published: date | None, *, today: date, recency_days: int, unknown_date_policy: str
) -> str | None:
    """Why a source fails the recency rule, or None if it passes."""
    if published is None:
        if unknown_date_policy == "exclude":
            return "publication date unknown"
        return None
    cutoff = today - timedelta(days=recency_days)
    if published < cutoff:
        return (
            f"outdated: published {published.isoformat()}, "
            f"older than the {recency_days}-day window (cutoff {cutoff.isoformat()})"
        )
    return None


@dataclass
class RuleOutcome:
    result: SearchResult
    exclusion_reason: str | None  # None = passed all rules
    rule: ExclusionRule | None = None  # which rule excluded it


@dataclass
class RuleReport:
    outcomes: list[RuleOutcome] = field(default_factory=list)  # new results, kept or excluded
    duplicates: list[SearchResult] = field(default_factory=list)  # already known URLs


def apply_rules(
    results: list[SearchResult],
    *,
    existing: list[Source],
    today: date,
    recency_days: int,
    config: FilteringConfig,
) -> RuleReport:
    """Run the code rules on one search's results.

    Order: duplicate, recency, content length, domain cap.

    `existing` is every source already in the session (kept or excluded), so the same page is
    never processed twice.
    """
    report = RuleReport()
    seen = {normalize_url(s.url) for s in existing}
    kept_per_domain: dict[str, int] = {}
    for s in existing:
        if s.status == SourceStatus.KEPT:
            kept_per_domain[s.domain] = kept_per_domain.get(s.domain, 0) + 1

    for result in results:
        key = normalize_url(result.url)
        if key in seen:
            report.duplicates.append(result)
            continue
        seen.add(key)

        rule: ExclusionRule | None = None
        reason = recency_problem(
            result.published_date,
            today=today,
            recency_days=recency_days,
            unknown_date_policy=config.unknown_date_policy,
        )
        if reason is not None:
            rule = "recency"
        elif len(result.content.strip()) < config.min_content_chars:
            rule = "content"
            reason = (
                f"too little content ({len(result.content.strip())} characters, "
                f"minimum {config.min_content_chars})"
            )
        domain = domain_of(result.url)
        if reason is None and kept_per_domain.get(domain, 0) >= config.max_sources_per_domain:
            rule = "domain_cap"
            reason = (
                f"already {config.max_sources_per_domain} sources from {domain}; "
                "capped for source diversity"
            )
        if reason is None:
            kept_per_domain[domain] = kept_per_domain.get(domain, 0) + 1
        report.outcomes.append(RuleOutcome(result=result, exclusion_reason=reason, rule=rule))

    return report
