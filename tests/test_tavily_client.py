import json
from datetime import date

import httpx
import pytest

from app.models import SearchMode
from app.search.base import SearchError, SearchQuery
from app.search.tavily_client import TavilySearchClient, parse_published_date


def client_returning(status: int, body: object, seen: list[httpx.Request]) -> TavilySearchClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TavilySearchClient(api_key="tvly-test", http_client=http)


async def test_maps_results_and_sends_expected_request() -> None:
    seen: list[httpx.Request] = []
    body = {
        "results": [
            {
                "url": "https://a.com/x",
                "title": "A",
                "content": "snippet",
                "raw_content": "full text",
                "published_date": "Tue, 05 May 2026 10:00:00 GMT",
                "score": 0.8,
            },
            {"url": "https://b.com/y", "title": "B", "content": "only snippet"},
        ]
    }
    client = client_returning(200, body, seen)
    results = await client.search(SearchQuery("ai news", SearchMode.NEWS, max_results=5))

    assert results[0].content == "full text"
    assert results[0].published_date == date(2026, 5, 5)
    assert results[1].content == "only snippet"  # falls back to the snippet
    assert results[1].published_date is None

    sent = json.loads(seen[0].content)
    assert sent["topic"] == "news"
    assert sent["include_published_date"] is True
    assert sent["max_results"] == 5
    assert seen[0].headers["Authorization"] == "Bearer tvly-test"


async def test_http_error_becomes_search_error() -> None:
    client = client_returning(429, {"detail": "rate limited"}, [])
    with pytest.raises(SearchError, match="429"):
        await client.search(SearchQuery("x"))


async def test_bad_body_becomes_search_error() -> None:
    client = client_returning(200, {"unexpected": True}, [])
    with pytest.raises(SearchError, match="format"):
        await client.search(SearchQuery("x"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-03-04", date(2026, 3, 4)),
        ("2026-03-04T10:00:00Z", date(2026, 3, 4)),
        ("Wed, 04 Mar 2026 10:00:00 GMT", date(2026, 3, 4)),
        ("not a date", None),
        (None, None),
    ],
)
def test_parse_published_date(value: str | None, expected: date | None) -> None:
    assert parse_published_date(value) == expected
