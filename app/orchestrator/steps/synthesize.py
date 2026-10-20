"""SYNTHESIZING: write the final report. Every statement must cite summarized sources."""

from pydantic import BaseModel

from app.llm.base import StructuredOutputError
from app.models import Actor, CitedStatement, Report, ReportSection, ResearchSession
from app.orchestrator.citations import citation_problems, mark_supported
from app.orchestrator.deps import AgentDeps
from app.orchestrator.steps.common import (
    call_llm_step,
    research_context,
    research_questions_text,
    wrap_summary,
)


class CitedClaim(BaseModel):
    text: str
    source_ids: list[str]


class SectionOutput(BaseModel):
    heading: str
    statements: list[CitedClaim]


class SynthesisOutput(BaseModel):
    title: str
    executive_summary: str
    key_takeaways: list[CitedClaim]
    sections: list[SectionOutput]
    open_questions: list[str]
    limitations: list[str]
    suggested_next_topics: list[str]


def all_claims(output: SynthesisOutput) -> list[CitedClaim]:
    return [*output.key_takeaways, *(c for s in output.sections for c in s.statements)]


def synthesis_problems(output: SynthesisOutput, allowed_ids: set[str]) -> list[str]:
    return citation_problems([(c.text, c.source_ids) for c in all_claims(output)], allowed_ids)


def build_report(
    output: SynthesisOutput, session: ResearchSession, allowed_ids: set[str]
) -> Report:
    def cited(claim: CitedClaim) -> CitedStatement:
        statement = CitedStatement(text=claim.text, source_ids=claim.source_ids)
        return mark_supported(statement, allowed_ids)

    return Report(
        title=output.title,
        executive_summary=output.executive_summary,
        key_takeaways=[cited(c) for c in output.key_takeaways],
        sections=[
            ReportSection(heading=s.heading, statements=[cited(c) for c in s.statements])
            for s in output.sections
        ],
        contradictions=[
            c
            for c in session.contradictions
            if c.source_a in allowed_ids and c.source_b in allowed_ids
        ],
        open_questions=output.open_questions,
        assumptions=list(session.assumptions),
        limitations=output.limitations,
        suggested_next_topics=output.suggested_next_topics,
    )


def empty_report(session: ResearchSession) -> Report:
    """No usable sources: say so plainly instead of asking the LLM to write without evidence."""
    return Report(
        title=f"Research on: {session.topic}",
        executive_summary="No usable sources were found, so no findings can be reported.",
        key_takeaways=[],
        sections=[],
        assumptions=list(session.assumptions),
        limitations=[
            "Every source found was excluded (outdated, irrelevant or unreadable) or could not "
            "be summarized. Try a wider recency window or a broader topic."
        ],
    )


async def run_synthesize(deps: AgentDeps, session: ResearchSession) -> Report:
    kept = {s.id for s in session.kept_sources()}
    summaries = [s for s in session.summaries if s.source_id in kept]
    if not summaries:
        report = empty_report(session)
        session.add_log(
            actor=Actor.AGENT,
            step="synthesize",
            action="wrote report without findings",
            decision="no summarized sources to cite",
        )
        return report

    allowed = {s.source_id for s in summaries}
    sources = {s.id: s for s in session.sources}
    contradictions = "\n".join(
        f"- {c.id} ({c.topic}): {c.source_a} says '{c.claim_a}', {c.source_b} says '{c.claim_b}'. "
        f"{c.explanation}"
        for c in session.contradictions
        if c.source_a in allowed and c.source_b in allowed
    )
    try:
        output = await call_llm_step(
            deps,
            session,
            "synthesize",
            SynthesisOutput,
            values={
                "context": research_context(deps, session),
                "research_questions": research_questions_text(session),
                "summaries": "\n\n".join(wrap_summary(sources[s.source_id], s) for s in summaries),
                "contradictions": contradictions or "(none found)",
            },
            validate=lambda out: synthesis_problems(out, allowed),
        )
    except StructuredOutputError as exc:
        # The report had the right shape but still cited unknown sources after the retries:
        # keep it and flag those statements as unsupported rather than failing the session.
        if not isinstance(exc.last_valid_shape, SynthesisOutput):
            raise
        output = exc.last_valid_shape

    report = build_report(output, session, allowed)
    statements = [*report.key_takeaways, *(c for s in report.sections for c in s.statements)]
    unsupported = sum(not s.supported for s in statements)
    session.add_log(
        actor=Actor.AGENT,
        step="synthesize",
        action="wrote final report",
        decision=f"{len(statements)} cited statements, {unsupported} flagged unsupported",
        reason=f"based on {len(summaries)} summarized sources and "
        f"{len(report.contradictions)} contradiction(s)",
    )
    return report
