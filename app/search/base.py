"""The web search interface. Tavily implements it for real; a fake implements it for tests."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.models import SearchMode


@dataclass(frozen=True)
class SearchQuery:
    query: str
    mode: SearchMode = SearchMode.GENERAL
    max_results: int = 6


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str  # short extract, used for relevance judging
    content: str  # full page text ("" if unavailable), used for summaries
    published_date: date | None  # None when the provider could not detect a date
    score: float = 0.0  # provider's own relevance score, for reference only


class SearchClient(Protocol):
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...


class SearchError(Exception):
    """The search provider failed (timeout, HTTP error, bad response)."""
