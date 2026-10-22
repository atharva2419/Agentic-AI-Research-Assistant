"""Render a finished session's report as Markdown with a numbered source list."""

from app.models import CitedStatement, ResearchSession


def _statement(s: CitedStatement) -> str:
    cites = " ".join(f"[{sid}]" for sid in s.source_ids)
    flag = " **(unsupported: citation could not be verified)**" if not s.supported else ""
    return f"- {s.text} {cites}{flag}".rstrip()


def report_to_markdown(session: ResearchSession) -> str:
    report = session.report
    if report is None:
        return f"# {session.topic}\n\n_No report yet (status: {session.status})._\n"

    lines = [f"# {report.title}", "", report.executive_summary, ""]
    if report.key_takeaways:
        lines += ["## Key takeaways", "", *map(_statement, report.key_takeaways), ""]
    for section in report.sections:
        lines += [f"## {section.heading}", "", *map(_statement, section.statements), ""]
    if report.contradictions:
        lines += ["## Contradictions between sources", ""]
        for c in report.contradictions:
            # Claims often end with their own period; strip it so sentences don't end in "..".
            lines.append(
                f"- **{c.topic}**: [{c.source_a}] says {c.claim_a.rstrip('.')}; "
                f"[{c.source_b}] says {c.claim_b.rstrip('.')}. {c.explanation}"
                + (f" _Likely cause: {c.likely_cause}_" if c.likely_cause else "")
            )
        lines.append("")
    for heading, items in (
        ("Open questions", report.open_questions),
        ("Assumptions", report.assumptions),
        ("Limitations", report.limitations),
        ("Suggested next topics", report.suggested_next_topics),
    ):
        if items:
            lines += [f"## {heading}", "", *(f"- {item}" for item in items), ""]

    cited = {sid for s in _all_statements(session) for sid in s.source_ids}
    sources = [s for s in session.sources if s.id in cited]
    if sources:
        lines += ["## Sources", ""]
        for s in sources:
            published = s.published_date.isoformat() if s.published_date else "date unknown"
            lines.append(f"- [{s.id}] {s.title} — {s.domain}, {published}. <{s.url}>")
        lines.append("")
    return "\n".join(lines)


def _all_statements(session: ResearchSession) -> list[CitedStatement]:
    if session.report is None:
        return []
    report = session.report
    return [*report.key_takeaways, *(c for s in report.sections for c in s.statements)]
