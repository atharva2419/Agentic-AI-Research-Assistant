"""Database tables (SQLAlchemy 2.0 typed ORM) and engine setup.

Two tables:
- `sessions`: the whole ResearchSession as one JSON column, plus the fields we filter or sort on
  as real columns. Little code, still queryable; on Postgres `state_json` would be JSONB.
- `memory_items`: what the agent remembers from each finished session (small, per user, with TTL).

The schema is created and changed only by Alembic migrations (migrations/versions/), never by
`create_all()`. A test checks that these models and the migrations stay identical.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
    event,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    topic: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    cost_usd: Mapped[float] = mapped_column(Float)
    page_text_removed: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state_json: Mapped[str] = mapped_column(Text)


class MemoryRow(Base):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("sessions.id", ondelete="CASCADE"), unique=True
    )
    topic: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    key_findings: Mapped[list[str]] = mapped_column(JSON)
    source_urls: Mapped[list[str]] = mapped_column(JSON)
    suggested_topics: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; everything in this app is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///") and not database_url.endswith(":memory:"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: Any, _record: Any) -> None:
            # SQLite ignores ON DELETE CASCADE unless this is switched on per connection.
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
