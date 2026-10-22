"""Where research sessions are kept: SQL (real) or in memory (tests and quick runs).

Both implement `SessionStore`, so the runner and routes don't know which one they use.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Actor, ResearchSession, Status
from app.storage.db import SessionRow, as_utc

FINISHED = (Status.DONE, Status.FAILED)


@dataclass(frozen=True)
class SessionInfo:
    """The columns needed for a session list, without loading the (large) session JSON."""

    id: str
    user_id: str
    topic: str
    status: Status
    mode: str
    created_at: datetime
    cost_usd: float


class SessionStore(Protocol):
    def save(self, session: ResearchSession) -> None: ...

    def get(self, session_id: str) -> ResearchSession | None: ...

    def list_sessions(self, user_id: str | None = None) -> list[SessionInfo]: ...

    def list_unfinished(self) -> list[ResearchSession]: ...

    def delete(self, session_id: str) -> bool: ...

    def remove_old_page_text(self, finished_before: datetime) -> int: ...


def _info(session: ResearchSession) -> SessionInfo:
    return SessionInfo(
        id=session.id,
        user_id=session.user_id,
        topic=session.topic,
        status=session.status,
        mode=session.mode.value,
        created_at=session.created_at,
        cost_usd=session.budget.cost_usd,
    )


def strip_page_text(session: ResearchSession, retention_days: int) -> bool:
    """Retention policy: drop full page text, keep everything else (summaries, verified quotes,
    the report, the log). Returns True if anything was removed."""
    removed = sum(1 for s in session.sources if s.content)
    for source in session.sources:
        source.content = ""
    if removed:
        session.add_log(
            actor=Actor.SYSTEM,
            step="retention",
            action=f"removed stored page text of {removed} source(s)",
            decision="summaries, quotes, report and log are kept",
            reason=f"retention policy: page text is kept for {retention_days} days",
        )
    return bool(removed)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ResearchSession] = {}

    def save(self, session: ResearchSession) -> None:
        self._sessions[session.id] = session

    def get(self, session_id: str) -> ResearchSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self, user_id: str | None = None) -> list[SessionInfo]:
        sessions = [s for s in self._sessions.values() if user_id is None or s.user_id == user_id]
        return [_info(s) for s in sorted(sessions, key=lambda s: s.created_at, reverse=True)]

    def list_unfinished(self) -> list[ResearchSession]:
        return [s for s in self._sessions.values() if s.status not in FINISHED]

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def remove_old_page_text(self, finished_before: datetime) -> int:
        return 0  # in-memory sessions don't outlive the process


class SqlSessionStore:
    def __init__(self, engine: Engine, retention_days: int = 30) -> None:
        self._db = sessionmaker(engine, expire_on_commit=False)
        self._retention_days = retention_days

    def save(self, session: ResearchSession) -> None:
        with self._db.begin() as db:
            row = db.get(SessionRow, session.id)
            if row is None:
                row = SessionRow(id=session.id, created_at=session.created_at)
                db.add(row)
            row.user_id = session.user_id
            row.topic = session.topic
            row.status = session.status.value
            row.mode = session.mode.value
            row.cost_usd = session.budget.cost_usd
            row.updated_at = session.updated_at
            row.state_json = session.model_dump_json()

    def get(self, session_id: str) -> ResearchSession | None:
        with self._db() as db:
            row = db.get(SessionRow, session_id)
            return ResearchSession.model_validate_json(row.state_json) if row else None

    def list_sessions(self, user_id: str | None = None) -> list[SessionInfo]:
        query = select(
            SessionRow.id,
            SessionRow.user_id,
            SessionRow.topic,
            SessionRow.status,
            SessionRow.mode,
            SessionRow.created_at,
            SessionRow.cost_usd,
        ).order_by(SessionRow.created_at.desc())
        if user_id is not None:
            query = query.where(SessionRow.user_id == user_id)
        with self._db() as db:
            return [
                SessionInfo(
                    id=r.id,
                    user_id=r.user_id,
                    topic=r.topic,
                    status=Status(r.status),
                    mode=r.mode,
                    created_at=as_utc(r.created_at),
                    cost_usd=r.cost_usd,
                )
                for r in db.execute(query)
            ]

    def list_unfinished(self) -> list[ResearchSession]:
        query = select(SessionRow.state_json).where(
            SessionRow.status.not_in([s.value for s in FINISHED])
        )
        with self._db() as db:
            return [ResearchSession.model_validate_json(j) for j in db.scalars(query)]

    def delete(self, session_id: str) -> bool:
        with self._db.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return False
            db.delete(row)  # its memory item goes too (ON DELETE CASCADE)
            return True

    def remove_old_page_text(self, finished_before: datetime) -> int:
        """Apply the retention policy to sessions that finished before the cutoff."""
        query = select(SessionRow).where(
            SessionRow.status.in_([s.value for s in FINISHED]),
            SessionRow.page_text_removed.is_(False),
            SessionRow.updated_at < finished_before,
        )
        count = 0
        with self._db.begin() as db:
            for row in db.scalars(query):
                session = ResearchSession.model_validate_json(row.state_json)
                strip_page_text(session, self._retention_days)
                row.state_json = session.model_dump_json()
                row.page_text_removed = True
                count += 1
        return count
