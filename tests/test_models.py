import pytest
from pydantic import TypeAdapter, ValidationError

from app.models import (
    Actor,
    AnswerQuestions,
    ClarifyingQuestion,
    ExcludeSource,
    ResearchSession,
    SetRecency,
    Source,
    SourceStatus,
    Status,
    UserCommand,
)


def make_session() -> ResearchSession:
    return ResearchSession(user_id="u1", topic="AI in journalism")


def test_new_session_defaults() -> None:
    session = make_session()
    assert session.status == Status.CREATED
    assert session.paused is False
    assert session.settings.recency_days == 365
    assert session.log == []


def test_add_log_numbers_entries_in_order() -> None:
    session = make_session()
    first = session.add_log(actor=Actor.AGENT, step="plan", action="created plan")
    second = session.add_log(actor=Actor.USER, step="override", action="excluded source")
    assert (first.seq, second.seq) == (1, 2)
    assert session.log[1].actor == Actor.USER


def test_kept_sources_skips_excluded() -> None:
    session = make_session()
    session.sources = [
        Source(id="S1", url="https://a.com/1", title="A", domain="a.com"),
        Source(
            id="S2",
            url="https://b.com/1",
            title="B",
            domain="b.com",
            status=SourceStatus.EXCLUDED,
        ),
    ]
    assert [s.id for s in session.kept_sources()] == ["S1"]
    assert session.get_source("S2") is not None
    assert session.get_source("S9") is None


def test_pending_questions() -> None:
    session = make_session()
    session.questions = [
        ClarifyingQuestion(
            id="q1", question="Region?", why_it_matters="x", assumption_if_skipped="US"
        ),
        ClarifyingQuestion(
            id="q2",
            question="Period?",
            why_it_matters="y",
            assumption_if_skipped="1y",
            skipped=True,
        ),
    ]
    assert [q.id for q in session.pending_questions()] == ["q1"]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchSession.model_validate({"user_id": "u1", "topic": "x", "surprise": 1})


def test_relevance_score_must_be_between_0_and_1() -> None:
    with pytest.raises(ValidationError):
        Source(id="S1", url="u", title="t", domain="d", relevance_score=1.5)


def test_user_command_is_parsed_by_type() -> None:
    adapter: TypeAdapter[UserCommand] = TypeAdapter(UserCommand)
    command = adapter.validate_python({"type": "exclude_source", "source_id": "S3"})
    assert isinstance(command, ExcludeSource)
    answers = adapter.validate_python({"type": "answer_questions", "answers": {"q1": None}})
    assert isinstance(answers, AnswerQuestions)
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "delete_everything"})


def test_set_recency_rejects_zero_days() -> None:
    with pytest.raises(ValidationError):
        SetRecency(recency_days=0)


def test_session_round_trips_through_json() -> None:
    session = make_session()
    session.add_log(actor=Actor.AGENT, step="clarify", action="asked questions")
    restored = ResearchSession.model_validate_json(session.model_dump_json())
    assert restored == session
