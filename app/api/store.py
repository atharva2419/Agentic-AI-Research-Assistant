"""Where sessions are kept. In memory for now; Phase 7 adds a SQLite implementation behind the
same interface."""

from typing import Protocol

from app.models import ResearchSession


class SessionStore(Protocol):
    def save(self, session: ResearchSession) -> None: ...

    def get(self, session_id: str) -> ResearchSession | None: ...

    def list_sessions(self, user_id: str | None = None) -> list[ResearchSession]: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ResearchSession] = {}

    def save(self, session: ResearchSession) -> None:
        self._sessions[session.id] = session

    def get(self, session_id: str) -> ResearchSession | None:
        return self._sessions.get(session_id)

    def list_sessions(self, user_id: str | None = None) -> list[ResearchSession]:
        sessions = [s for s in self._sessions.values() if user_id is None or s.user_id == user_id]
        return sorted(sessions, key=lambda s: s.created_at, reverse=True)
