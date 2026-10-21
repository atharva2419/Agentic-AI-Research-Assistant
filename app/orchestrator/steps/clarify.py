"""CLARIFYING: decide whether the topic is ambiguous and, if so, ask a few questions."""

from pydantic import BaseModel

from app.models import Actor, ClarifyingQuestion, ResearchSession
from app.orchestrator.deps import AgentDeps
from app.orchestrator.steps.common import call_llm_step, research_context
from app.orchestrator.steps.questions import QuestionOutput, add_questions


class ClarifyOutput(BaseModel):
    is_ambiguous: bool
    reasoning: str
    questions: list[QuestionOutput]


def clarify_problems(output: ClarifyOutput, max_questions: int) -> list[str]:
    problems = []
    if len(output.questions) > max_questions:
        problems.append(f"ask at most {max_questions} questions; you asked {len(output.questions)}")
    if output.is_ambiguous and not output.questions:
        problems.append("is_ambiguous is true but no questions were asked")
    if not output.is_ambiguous and output.questions:
        problems.append("is_ambiguous is false, so questions must be empty")
    for i, q in enumerate(output.questions, start=1):
        if not q.assumption_if_skipped.strip():
            problems.append(f"question {i} needs an assumption_if_skipped")
    return problems


async def run_clarify(deps: AgentDeps, session: ResearchSession) -> list[ClarifyingQuestion]:
    """Returns the questions asked (empty if the topic is clear enough to plan)."""
    max_questions = deps.blueprint.limits.max_clarifying_questions
    if max_questions == 0:
        return []
    output = await call_llm_step(
        deps,
        session,
        "clarify",
        ClarifyOutput,
        values={
            "context": research_context(deps, session),
            "max_questions": str(max_questions),
        },
        validate=lambda out: clarify_problems(out, max_questions),
    )
    if not output.questions:
        session.add_log(
            actor=Actor.AGENT,
            step="clarify",
            action="topic is clear enough to plan",
            decision="no questions",
            reason=output.reasoning,
        )
        return []
    session.add_log(
        actor=Actor.AGENT,
        step="clarify",
        action="topic is ambiguous",
        decision=f"asking {len(output.questions)} question(s)",
        reason=output.reasoning,
    )
    return add_questions(session, output.questions, origin="clarify")
