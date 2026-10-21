"""Offline search: made-up but realistic results for any query. No network, no API key.

Each query returns four results designed to exercise the pipeline: three recent articles (two of
which disagree on a number, so the cross-check finds a contradiction), one outdated article that
the recency rule excludes, and one thin "listicle" the relevance judge rejects.
"""

import asyncio
import hashlib
from datetime import date, timedelta

from app.search.base import SearchQuery, SearchResult

OUTLETS = [
    "dailyledger.example",
    "policywire.example",
    "researchdesk.example",
    "metroherald.example",
]


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _article(query: str, outlet: str, share: int, stance: str) -> str:
    return (
        f"A new analysis of {query} finds that {share}% of organisations surveyed have changed "
        f"their approach in the past year. {stance} "
        f"Researchers interviewed practitioners across several regions and reviewed public data "
        f"published during the period. The report notes that adoption varies widely by size and "
        f"budget, and that smaller organisations report more difficulty. Critics say the evidence "
        f"is still early and that long-term effects remain unclear. The authors at {outlet} call "
        f"for more transparent reporting and independent audits before drawing firm conclusions."
    )


class OfflineSearch:
    def __init__(self, today: date | None = None, delay_s: float = 0.4) -> None:
        self._today = today or date.today()
        self._delay_s = delay_s

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        await asyncio.sleep(self._delay_s)
        seed = _seed(query.query)
        slug = "-".join(query.query.lower().split())[:60]
        first = OUTLETS[seed % len(OUTLETS)]
        second = OUTLETS[(seed + 1) % len(OUTLETS)]
        results = [
            SearchResult(
                url=f"https://{first}/{slug}",
                title=f"Survey: how {query.query} is changing",
                snippet=f"Survey finds 62% report changes related to {query.query}.",
                content=_article(query.query, first, 62, "Most respondents expect growth."),
                published_date=self._today - timedelta(days=20 + seed % 60),
            ),
            SearchResult(
                url=f"https://{second}/{slug}-analysis",
                title=f"Analysis: the real impact of {query.query}",
                snippet=f"Independent analysis puts the figure at 35% for {query.query}.",
                content=_article(
                    query.query, second, 35, "The authors find the impact overstated."
                ),
                published_date=self._today - timedelta(days=90 + seed % 90),
            ),
            SearchResult(
                url=f"https://archive.example/{slug}-2019",
                title=f"Early look at {query.query} (archive)",
                snippet="An early article from several years ago.",
                content=_article(query.query, "archive.example", 10, "Adoption was rare then."),
                published_date=self._today - timedelta(days=5 * 365),
            ),
            SearchResult(
                url=f"https://listicles.example/top-10-{slug}",
                title=f"Top 10 facts about {query.query} (listicle)",
                snippet="You won't believe number 7.",
                content="Top 10 facts. " * 40,
                published_date=self._today - timedelta(days=10),
            ),
        ]
        return results[: query.max_results]
