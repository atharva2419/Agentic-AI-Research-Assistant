"""Optional priority keywords from the user.

They are guidance, not filters: prompts are told to favour them, and code measures how many kept
sources mention each one, so the gap check can replan for a keyword nothing covers yet. No source
is ever excluded for missing a keyword.
"""

from app.models import Source, SourceStatus

MAX_KEYWORDS = 8
MAX_KEYWORD_LENGTH = 40


def normalize_keywords(raw: list[str]) -> list[str]:
    """Trim, drop empties and case-insensitive duplicates, keep the user's order and spelling."""
    keywords: list[str] = []
    seen: set[str] = set()
    for keyword in raw:
        cleaned = " ".join(keyword.split())
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            keywords.append(cleaned)
    return keywords


def keyword_coverage(keywords: list[str], sources: list[Source]) -> dict[str, list[str]]:
    """For each keyword, the IDs of kept sources that mention it (title, snippet or page text)."""
    coverage: dict[str, list[str]] = {}
    kept = [s for s in sources if s.status == SourceStatus.KEPT]
    for keyword in keywords:
        needle = keyword.lower()
        coverage[keyword] = [
            s.id
            for s in kept
            if needle in s.title.lower()
            or needle in s.snippet.lower()
            or needle in s.content.lower()
        ]
    return coverage
