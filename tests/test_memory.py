"""Long-term memory: retrieval, remember/recall/suggest, TTL, and its effect on the agent."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.memory.retrieval import TfidfRetriever, tokenize
from app.memory.service import MemoryService
from app.memory.store import InMemoryMemoryStore, MemoryStore, SqlMemoryStore
from app.models import (
    CitedStatement,
    Mode,
    Report,
    ResearchSession,
    Source,
    Status,
    utc_now,
)
from app.orchestrator.orchestrator import Orchestrator
from app.search.fake import FakeSearch
from app.storage.db import make_engine
from app.storage.migrate import upgrade_to_head
from app.storage.sessions import SqlSessionStore
from tests.helpers import BLUEPRINT, make_deps, make_session
from tests.test_orchestrator import fixture_search, scripted_llm

CONFIG = BLUEPRINT.memory
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=utc_now().tzinfo)


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def finished_session(
    topic: str, user_id: str = "u1", suggestions: list[str] | None = None
) -> ResearchSession:
    session = ResearchSession(user_id=user_id, topic=topic, status=Status.DONE)
    session.sources = [
        Source(id="S1", url="https://a.com/1", title="A", domain="a.com"),
        Source(id="S2", url="https://b.com/2", title="B", domain="b.com"),
    ]
    session.report = Report(
        title=topic,
        executive_summary=f"Summary about {topic}.",
        key_takeaways=[
            CitedStatement(text=f"{topic} finding one.", source_ids=["S1"]),
            CitedStatement(text="Unverified claim.", source_ids=[], supported=False),
        ],
        sections=[],
        suggested_next_topics=suggestions or [],
    )
    return session


def service(store: MemoryStore | None = None, clock: Clock | None = None) -> MemoryService:
    return MemoryService(store or InMemoryMemoryStore(), CONFIG, clock=clock or Clock())


# --- Retrieval ---------------------------------------------------------------------------------


def test_tokenize_drops_stopwords_and_plurals() -> None:
    assert tokenize("The impact of AI models on newsrooms") == ["impact", "ai", "model", "newsroom"]


def test_tfidf_ranks_the_closest_document_first() -> None:
    docs = ["AI in newsrooms and journalism jobs", "heat pumps in cold climates", "pizza recipes"]
    scores = TfidfRetriever().similarities("journalism and AI", docs)
    assert scores[0] > scores[1] and scores[0] > scores[2]
    assert scores[2] == 0.0


# --- Remember / recall / suggest ---------------------------------------------------------------


def test_remember_keeps_only_verified_findings_and_cited_urls() -> None:
    memory = service()
    item = memory.remember(finished_session("AI in journalism"))
    assert item is not None
    assert item.key_findings == ["AI in journalism finding one."]
    assert item.source_urls == ["https://a.com/1"]
    assert item.expires_at == NOW + timedelta(days=CONFIG.ttl_days)


def test_recall_finds_related_topics_and_skips_unrelated_ones() -> None:
    memory = service()
    memory.remember(finished_session("AI in journalism newsrooms"))
    memory.remember(finished_session("heat pumps in cold climates"))
    matches = memory.recall("u1", "generative AI and journalism jobs")
    assert [m.topic for m in matches] == ["AI in journalism newsrooms"]
    assert memory.recall("someone-else", "AI in journalism") == []  # memory is per user


def test_recall_excludes_the_session_itself() -> None:
    memory = service()
    session = finished_session("AI in journalism")
    memory.remember(session)
    assert memory.recall("u1", "AI in journalism", exclude_session_id=session.id) == []


def test_expired_memories_are_never_recalled_and_get_purged() -> None:
    clock = Clock()
    memory = service(clock=clock)
    memory.remember(finished_session("AI in journalism"))
    clock.now = NOW + timedelta(days=CONFIG.ttl_days + 1)
    assert memory.recall("u1", "AI in journalism") == []
    assert memory.purge_expired() == 1


def test_newer_memory_outranks_an_older_equally_similar_one() -> None:
    clock = Clock(NOW - timedelta(days=300))
    store = InMemoryMemoryStore()
    old_service = service(store, clock)
    old_service.remember(finished_session("AI in journalism"))
    clock.now = NOW
    service(store, clock).remember(finished_session("AI in journalism"))
    matches = service(store, clock).recall("u1", "AI in journalism")
    assert matches[0].created_at == NOW


def test_suggestions_skip_topics_already_researched() -> None:
    memory = service()
    memory.remember(
        finished_session(
            "AI in journalism",
            suggestions=[
                "AI in Journalism",  # nothing new: skipped
                "Regulation of AI in journalism",  # adds "regulation": kept
                "AI and local news",
                "AI and local news ",  # duplicate
            ],
        )
    )
    assert memory.suggestions("u1") == ["Regulation of AI in journalism", "AI and local news"]


def test_forget_is_scoped_to_the_user() -> None:
    memory = service()
    item = memory.remember(finished_session("AI in journalism"))
    assert item is not None
    assert not memory.forget("someone-else", item.id)
    assert memory.forget("u1", item.id)
    assert memory.list_items("u1") == []


# --- SQL store ---------------------------------------------------------------------------------


@pytest.fixture
def sql_store(tmp_path: Path) -> tuple[SqlMemoryStore, SqlSessionStore]:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    upgrade_to_head(url)
    engine = make_engine(url)
    return SqlMemoryStore(engine), SqlSessionStore(engine)


def test_sql_memory_upserts_per_session_and_expires(
    sql_store: tuple[SqlMemoryStore, SqlSessionStore],
) -> None:
    memories, sessions = sql_store
    session = finished_session("AI in journalism")
    sessions.save(session)  # memory rows reference a session row
    memory = service(memories)
    memory.remember(session)
    session.report.executive_summary = "Revised."  # type: ignore[union-attr]
    memory.remember(session)  # a rewritten report replaces the memory
    [item] = memory.list_items("u1")
    assert item.summary == "Revised."
    assert item.created_at == NOW  # timezone survives the SQLite round trip

    later = service(memories, Clock(NOW + timedelta(days=CONFIG.ttl_days + 1)))
    assert later.list_items("u1") == []
    assert later.purge_expired() == 1


# --- Effect on the agent -----------------------------------------------------------------------


async def test_new_session_recalls_past_research_and_the_planner_sees_it() -> None:
    memory = service()
    memory.remember(finished_session("AI newsroom adoption and journalism jobs"))
    llm = scripted_llm()
    deps = make_deps(llm, fixture_search())
    deps.memory = memory
    session = await Orchestrator(deps).run_until_blocked(make_session(Mode.AUTONOMOUS))

    assert [m.topic for m in session.related_memory] == ["AI newsroom adoption and journalism jobs"]
    plan_prompt = llm.calls_for("plan")[0].messages[0].content
    assert "From past research by this user" in plan_prompt
    assert "AI newsroom adoption and journalism jobs (researched " in plan_prompt
    assert any(e.action == "saved findings to long-term memory" for e in session.log)
    assert len(memory.list_items("u1")) == 2  # this session was remembered too


async def test_no_memory_configured_means_no_memory_steps() -> None:
    deps = make_deps(scripted_llm(), FakeSearch())
    assert deps.memory is None
    session = await Orchestrator(deps).run_until_blocked(make_session())
    assert not any(e.step == "memory" for e in session.log)
