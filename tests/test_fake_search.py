from datetime import date

import pytest

from app.models import SearchMode
from app.search.base import SearchError, SearchQuery, SearchResult
from app.search.fake import FakeSearch

RESULT = SearchResult(
    url="https://example.com/a",
    title="A",
    snippet="snippet",
    content="content",
    published_date=date(2026, 5, 1),
)


async def test_returns_fixture_and_records_query() -> None:
    search = FakeSearch(results={"ai news": [RESULT, RESULT]})
    results = await search.search(SearchQuery("ai news", SearchMode.NEWS, max_results=1))
    assert results == [RESULT]
    assert search.queries[0].mode == SearchMode.NEWS


async def test_unknown_query_uses_default() -> None:
    search = FakeSearch(default=[RESULT])
    assert await search.search(SearchQuery("anything")) == [RESULT]


async def test_simulated_failure() -> None:
    search = FakeSearch(failing_queries={"boom"})
    with pytest.raises(SearchError):
        await search.search(SearchQuery("boom"))
