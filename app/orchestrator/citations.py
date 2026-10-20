"""Code checks on what the LLM wrote: are citations real, are quotes really in the source?"""

import re

from app.models import CitedStatement, Quote

# Curly quotes (U+2018, U+2019, U+201C, U+201D) -> straight quotes.
_QUOTE_CHARS = str.maketrans({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})


def citation_problems(statements: list[tuple[str, list[str]]], allowed_ids: set[str]) -> list[str]:
    """Problems with (text, source_ids) pairs: no citation, or a citation to an unknown source."""
    problems = []
    for text, source_ids in statements:
        preview = text[:60] + ("..." if len(text) > 60 else "")
        if not source_ids:
            problems.append(f'statement "{preview}" has no citation; cite at least one source ID')
        unknown = [sid for sid in source_ids if sid not in allowed_ids]
        if unknown:
            problems.append(
                f'statement "{preview}" cites unknown source IDs {unknown}; '
                f"only these exist: {sorted(allowed_ids)}"
            )
    return problems


def mark_supported(statement: CitedStatement, allowed_ids: set[str]) -> CitedStatement:
    """Keep only real citations. A statement is supported only if all its citations were real
    and at least one remains. Unsupported statements are flagged, never silently dropped."""
    valid = [sid for sid in statement.source_ids if sid in allowed_ids]
    supported = bool(valid) and len(valid) == len(statement.source_ids)
    return CitedStatement(text=statement.text, source_ids=valid, supported=supported)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTE_CHARS)).strip().lower()


def verify_quotes(quotes: list[Quote], content: str) -> tuple[list[Quote], list[Quote]]:
    """Split quotes into (found word for word in content, not found). Not-found quotes are
    likely hallucinated and are removed."""
    haystack = _normalize(content)
    found: list[Quote] = []
    missing: list[Quote] = []
    for quote in quotes:
        needle = _normalize(quote.text.strip("\"' "))
        (found if needle and needle in haystack else missing).append(quote)
    return found, missing
