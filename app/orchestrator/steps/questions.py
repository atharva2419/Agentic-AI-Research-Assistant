"""Clarifying questions: the shared LLM schema and the code that records answers and skips."""

from typing import Literal

from pydantic import BaseModel

from app.models import Actor, ClarifyingQuestion, Mode, ResearchSession


class QuestionOutput(BaseModel):
    question: str
    why_it_matters: str
    suggested_options: list[str]
    assumption_if_skipped: str


def add_questions(
    session: ResearchSession,
    questions: list[QuestionOutput],
    origin: Literal["clarify", "gap_check"],
) -> list[ClarifyingQuestion]:
    added = []
    for q in questions:
        question = ClarifyingQuestion(
            id=f"q{len(session.questions) + 1}",
            question=q.question,
            why_it_matters=q.why_it_matters,
            suggested_options=q.suggested_options,
            assumption_if_skipped=q.assumption_if_skipped,
            origin=origin,
        )
        session.questions.append(question)
        added.append(question)
        session.add_log(
            actor=Actor.AGENT,
            step=origin,
            action=f"asked {question.id}: {question.question}",
            decision=f"if skipped, assume: {question.assumption_if_skipped}",
            reason=question.why_it_matters,
            details=question.model_dump(),
        )
    return added


def skip_question(session: ResearchSession, question: ClarifyingQuestion, actor: Actor) -> None:
    """A skipped question becomes a stated assumption that every later prompt sees."""
    question.skipped = True
    session.assumptions.append(question.assumption_if_skipped)
    who = "user skipped" if actor == Actor.USER else "autonomous mode: did not wait for"
    session.add_log(
        actor=actor,
        step="clarify",
        action=f"{who} {question.id}",
        decision=f"assuming: {question.assumption_if_skipped}",
        reason=question.question,
    )


def answer_question(session: ResearchSession, question: ClarifyingQuestion, answer: str) -> None:
    question.answer = answer
    session.add_log(
        actor=Actor.USER,
        step="clarify",
        action=f"answered {question.id}",
        decision=answer,
        reason=question.question,
    )


def auto_resolve_if_autonomous(session: ResearchSession) -> bool:
    """In autonomous mode the agent doesn't wait: pending questions are skipped with their
    stated assumptions. Returns True if questions are still waiting for the user."""
    pending = session.pending_questions()
    if session.mode == Mode.AUTONOMOUS:
        for question in pending:
            skip_question(session, question, Actor.AGENT)
        return False
    return bool(pending)
