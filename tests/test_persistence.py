"""Phase 7 end to end over HTTP: sessions and memory survive a server restart (SQLite + Alembic),
interrupted sessions come back paused, memory endpoints, deleting a session."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.models import Mode, ResearchSession
from app.storage.db import make_engine
from app.storage.migrate import upgrade_to_head
from app.storage.sessions import SqlSessionStore
from app.wiring import Wiring
from tests.helpers import TODAY, make_deps


async def _noop() -> None:
    return None


@contextmanager
def server(database_url: str) -> Iterator[TestClient]:
    """One server process: startup (migrations, recovery) on enter, shutdown on exit."""
    deps = make_deps(OfflineLLM(delay_s=0), OfflineSearch(today=TODAY, delay_s=0))
    app = create_app(Wiring(deps=deps, offline=True, close=_noop), database_url=database_url)
    with TestClient(app) as client:
        yield client


def wait_for(
    client: TestClient, session_id: str, done: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    for _ in range(300):
        session: dict[str, Any] = client.get(f"/api/sessions/{session_id}").json()
        if done(session):
            return session
        time.sleep(0.01)
    raise AssertionError(f"timed out at status {session['status']}")


def url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'research.db').as_posix()}"


def test_sessions_and_memory_survive_a_restart(tmp_path: Path) -> None:
    with server(url(tmp_path)) as client:
        body = {"topic": "AI in journalism", "mode": "autonomous", "user_id": "atharva"}
        session_id = client.post("/api/sessions", json=body).json()["id"]
        wait_for(client, session_id, lambda s: s["status"] == "done")

    with server(url(tmp_path)) as client:  # a fresh process on the same database
        listed = client.get("/api/sessions", params={"user_id": "atharva"}).json()
        assert [s["id"] for s in listed] == [session_id]
        restored = client.get(f"/api/sessions/{session_id}").json()
        assert restored["report"]["key_takeaways"]

        [memory] = client.get("/api/users/atharva/memory").json()
        assert memory["session_id"] == session_id
        assert client.get("/api/users/atharva/suggestions").json()  # from the report
        related = client.get("/api/users/atharva/related", params={"topic": "AI and journalism"})
        assert [m["session_id"] for m in related.json()] == [session_id]

        # A new related session recalls the old one before planning.
        body = {"topic": "AI journalism jobs", "mode": "autonomous", "user_id": "atharva"}
        new_id = client.post("/api/sessions", json=body).json()["id"]
        new = wait_for(client, new_id, lambda s: s["status"] == "done")
        assert [m["session_id"] for m in new["related_memory"]] == [session_id]


def test_interrupted_session_comes_back_paused_and_resumes(tmp_path: Path) -> None:
    upgrade_to_head(url(tmp_path))
    interrupted = ResearchSession(user_id="demo", topic="heat pumps", mode=Mode.AUTONOMOUS)
    SqlSessionStore(make_engine(url(tmp_path))).save(interrupted)  # was running at shutdown

    with server(url(tmp_path)) as client:
        session = client.get(f"/api/sessions/{interrupted.id}").json()
        assert session["paused"] is True
        assert session["log"][-1]["step"] == "restart"
        time.sleep(0.05)
        assert client.get(f"/api/sessions/{interrupted.id}").json()["status"] == "created"

        client.post(f"/api/sessions/{interrupted.id}/commands", json={"type": "resume"})
        wait_for(client, interrupted.id, lambda s: s["status"] == "done")


def test_forget_and_delete(tmp_path: Path) -> None:
    with server(url(tmp_path)) as client:
        body = {"topic": "AI in journalism", "mode": "autonomous"}
        session_id = client.post("/api/sessions", json=body).json()["id"]
        wait_for(client, session_id, lambda s: s["status"] == "done")
        [memory] = client.get("/api/users/demo/memory").json()

        assert client.delete(f"/api/users/demo/memory/{memory['id']}").status_code == 204
        assert client.get("/api/users/demo/memory").json() == []
        assert client.delete(f"/api/users/demo/memory/{memory['id']}").status_code == 404

        assert client.delete(f"/api/sessions/{session_id}").status_code == 204
        assert client.get(f"/api/sessions/{session_id}").status_code == 404
        assert client.get("/api/sessions").json() == []
