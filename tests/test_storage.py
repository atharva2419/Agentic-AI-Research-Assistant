"""Database layer: Alembic migrations, the SQL session store, retention."""

from datetime import timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect

from app.memory.store import SqlMemoryStore
from app.models import MemoryItem, ResearchSession, Source, Status, utc_now
from app.storage.db import Base, make_engine
from app.storage.migrate import upgrade_to_head
from app.storage.sessions import SqlSessionStore


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    upgrade_to_head(url)
    return make_engine(url)


def session_with_text(status: Status = Status.DONE) -> ResearchSession:
    session = ResearchSession(user_id="u1", topic="heat pumps", status=status)
    session.sources = [
        Source(id="S1", url="https://a.com", title="A", domain="a.com", content="full page text")
    ]
    return session


def test_migration_creates_the_tables(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert {"sessions", "memory_items", "alembic_version"} <= tables


def test_models_and_migrations_do_not_drift(engine: Engine) -> None:
    """If someone changes app/storage/db.py without writing a migration, this fails."""
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_session_round_trip_and_listing(engine: Engine) -> None:
    store = SqlSessionStore(engine)
    session = session_with_text(Status.EXECUTING)
    store.save(session)
    session.status = Status.DONE
    session.budget.cost_usd = 0.21
    store.save(session)  # update, not a second row

    loaded = store.get(session.id)
    assert loaded == session
    [info] = store.list_sessions("u1")
    assert (info.id, info.status, info.cost_usd) == (session.id, Status.DONE, 0.21)
    assert store.list_sessions("someone-else") == []
    assert store.get("missing") is None


def test_list_unfinished(engine: Engine) -> None:
    store = SqlSessionStore(engine)
    running = session_with_text(Status.EXECUTING)
    store.save(running)
    store.save(session_with_text(Status.DONE))
    assert [s.id for s in store.list_unfinished()] == [running.id]


def test_retention_removes_page_text_once(engine: Engine) -> None:
    store = SqlSessionStore(engine, retention_days=30)
    old = session_with_text(Status.DONE)
    old.updated_at = utc_now() - timedelta(days=40)
    recent = session_with_text(Status.DONE)
    unfinished = session_with_text(Status.AWAITING_ANSWERS)
    unfinished.updated_at = old.updated_at
    for s in (old, recent, unfinished):
        store.save(s)

    assert store.remove_old_page_text(utc_now() - timedelta(days=30)) == 1
    stripped = store.get(old.id)
    assert stripped is not None and stripped.sources[0].content == ""
    assert stripped.log[-1].step == "retention"
    assert store.get(recent.id).sources[0].content == "full page text"  # type: ignore[union-attr]
    assert store.get(unfinished.id).sources[0].content  # type: ignore[union-attr]
    assert store.remove_old_page_text(utc_now()) == 1  # only `recent` is left to process


def test_deleting_a_session_deletes_its_memory(engine: Engine) -> None:
    sessions, memories = SqlSessionStore(engine), SqlMemoryStore(engine)
    session = session_with_text()
    sessions.save(session)
    now = utc_now()
    memories.save(
        MemoryItem(
            user_id="u1",
            session_id=session.id,
            topic="heat pumps",
            summary="s",
            key_findings=[],
            source_urls=[],
            expires_at=now + timedelta(days=1),
        )
    )
    assert sessions.delete(session.id)
    assert memories.list_items("u1", now) == []  # ON DELETE CASCADE
    assert not sessions.delete(session.id)
