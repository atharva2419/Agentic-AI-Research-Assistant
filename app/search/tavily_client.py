"""SearchClient implementation for Tavily (https://docs.tavily.com), using httpx."""

from datetime import date, datetime
from email.utils import parsedate_to_datetime

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.search.base import SearchError, SearchQuery, SearchResult

TAVILY_URL = "https://api.tavily.com/search"
MAX_CONTENT_CHARS = 20_000  # keep stored sessions a reasonable size


class TavilyResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    title: str = ""
    content: str = ""  # snippet
    raw_content: str | None = None  # full page text
    published_date: str | None = None
    score: float = 0.0


class TavilyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[TavilyResult]


def parse_published_date(value: str | None) -> date | None:
    """Tavily dates come as ISO 8601 or RFC 2822 ("Tue, 05 May 2026 10:00:00 GMT")."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


class TavilySearchClient:
    def __init__(
        self,
        api_key: str,
        timeout_s: float = 20.0,
        depth: str = "basic",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._depth = depth
        self._http = http_client or httpx.AsyncClient(timeout=timeout_s)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        payload = {
            "query": query.query,
            "topic": query.mode.value,
            "search_depth": self._depth,
            "max_results": query.max_results,
            "include_published_date": True,
            "include_raw_content": "text",
        }
        try:
            response = await self._http.post(TAVILY_URL, json=payload, headers=self._headers)
            response.raise_for_status()
            parsed = TavilyResponse.model_validate_json(response.content)
        except httpx.HTTPStatusError as exc:
            raise SearchError(f"Tavily returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise SearchError(f"could not reach Tavily: {type(exc).__name__}") from exc
        except ValidationError as exc:
            raise SearchError("unexpected response format from Tavily") from exc

        return [
            SearchResult(
                url=r.url,
                title=r.title,
                snippet=r.content,
                content=(r.raw_content or r.content)[:MAX_CONTENT_CHARS],
                published_date=parse_published_date(r.published_date),
                score=r.score,
            )
            for r in parsed.results
        ]

    async def aclose(self) -> None:
        await self._http.aclose()
