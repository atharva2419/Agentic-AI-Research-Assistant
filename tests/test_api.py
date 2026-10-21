"""The HTTP API, driven with FastAPI's TestClient and the offline demo pair (no network)."""

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.events import EventBus, ServerEvent, format_sse
from app.api.main import create_app
from app.demo.offline_llm import OfflineLLM
from app.demo.offline_search import OfflineSearch
from app.wiring import Wiring
from tests.helpers import TODAY, make_deps


async def _noop() -> None:
    return None


@pytest.fixture
def client() -> Iterator[TestClient]:
    deps = make_deps(OfflineLLM(delay_s=0), OfflineSearch(today=TODAY, delay_s=0))
    app = create_app(Wiring(deps=deps, offline=True, close=_noop))
    with TestClient(app) as test_client:  # `with` runs the app's startup and shutdown
        yield test_client


def wait_for(
    client: TestClient, session_id: str, done: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    """Poll until the background runner reaches the expected state (it runs on its own loop)."""
    for _ in range(200):
        session: dict[str, Any] = client.get(f"/api/sessions/{session_id}").json()
        if done(session):
            return session
        time.sleep(0.01)
    raise AssertionError(f"timed out; last status {session['status']}")


def status_is(*statuses: str) -> Callable[[dict[str, Any]], bool]:
    return lambda s: s["status"] in statuses


def test_health_reports_offline_mode(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "offline": True}


def test_full_supervised_session_over_http(client: TestClient) -> None:
    created = client.post("/api/sessions", json={"topic": "AI in journalism"})
    assert created.status_code == 201
    session_id = created.json()["id"]

    session = wait_for(client, session_id, status_is("awaiting_answers"))
    question_id = session["questions"][0]["id"]
    answer = {"type": "answer_questions", "answers": {question_id: "United States"}}
    assert client.post(f"/api/sessions/{session_id}/commands", json=answer).status_code == 200

    wait_for(client, session_id, status_is("awaiting_plan_approval"))
    approve = client.post(f"/api/sessions/{session_id}/commands", json={"type": "approve_plan"})
    assert approve.status_code == 200

    session = wait_for(client, session_id, status_is("done"))
    assert session["report"]["key_takeaways"]
    assert "content" not in session["sources"][0]  # page text is not sent to the browser
    assert any(entry["actor"] == "user" for entry in session["log"])

    report = client.get(f"/api/sessions/{session_id}/report.md")
    assert report.status_code == 200
    assert report.text.startswith("# ")

    listed = client.get("/api/sessions").json()
    assert [s["id"] for s in listed] == [session_id]


def test_autonomous_session_needs_no_commands(client: TestClient) -> None:
    created = client.post("/api/sessions", json={"topic": "heat pumps", "mode": "autonomous"})
    session = wait_for(client, created.json()["id"], status_is("done", "failed"))
    assert session["status"] == "done"


def test_command_that_does_not_fit_the_state_is_409(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={"topic": "AI in journalism"}).json()["id"]
    wait_for(client, session_id, status_is("awaiting_answers"))
    response = client.post(f"/api/sessions/{session_id}/commands", json={"type": "approve_plan"})
    assert response.status_code == 409
    assert "no plan waiting" in response.json()["detail"]


def test_unknown_command_type_is_422(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={"topic": "AI in journalism"}).json()["id"]
    response = client.post(f"/api/sessions/{session_id}/commands", json={"type": "delete_all"})
    assert response.status_code == 422


def test_unknown_session_is_404(client: TestClient) -> None:
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions/nope/commands", json={"type": "pause"}).status_code == 404


def test_invalid_new_session_is_422(client: TestClient) -> None:
    assert client.post("/api/sessions", json={"topic": "x"}).status_code == 422
    bad_window = {"topic": "AI in journalism", "recency_days": 0}
    assert client.post("/api/sessions", json=bad_window).status_code == 422


def test_pause_stops_the_runner_and_resume_finishes(client: TestClient) -> None:
    created = client.post("/api/sessions", json={"topic": "heat pumps", "mode": "autonomous"})
    session_id = created.json()["id"]
    client.post(f"/api/sessions/{session_id}/commands", json={"type": "pause"})
    paused = wait_for(client, session_id, lambda s: s["paused"])
    time.sleep(0.05)
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == paused["status"]

    client.post(f"/api/sessions/{session_id}/commands", json={"type": "resume"})
    assert wait_for(client, session_id, status_is("done"))["status"] == "done"


def test_event_stream_starts_with_a_snapshot(client: TestClient) -> None:
    session_id = client.post("/api/sessions", json={"topic": "AI in journalism"}).json()["id"]
    wait_for(client, session_id, status_is("awaiting_answers"))
    with client.stream("GET", f"/api/sessions/{session_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = response.iter_lines()
        assert next(lines) == "event: snapshot"
        assert next(lines).startswith('data: {"id": "' + session_id)


def test_sse_format() -> None:
    text = format_sse(ServerEvent(type="log", data={"seq": 1, "action": "searched"}))
    assert text == 'event: log\ndata: {"seq": 1, "action": "searched"}\n\n'


async def test_bus_fans_out_to_every_subscriber() -> None:
    bus = EventBus()
    async with bus.subscribe() as first, bus.subscribe() as second:
        bus.publish(ServerEvent(type="log", data={"seq": 1}))
        assert (await first.get()).data == {"seq": 1}
        assert (await second.get()).data == {"seq": 1}
    assert bus.subscriber_count == 0
