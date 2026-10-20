"""A fixture-based search client for tests: maps query text to fixed results."""

from app.search.base import SearchError, SearchQuery, SearchResult


class FakeSearch:
    def __init__(
        self,
        results: dict[str, list[SearchResult]] | None = None,
        default: list[SearchResult] | None = None,
        failing_queries: set[str] | None = None,
    ) -> None:
        self._results = results or {}
        self._default = default or []
        self._failing = failing_queries or set()
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.queries.append(query)
        if query.query in self._failing:
            raise SearchError(f"simulated failure for '{query.query}'")
        results = self._results.get(query.query, self._default)
        return results[: query.max_results]
