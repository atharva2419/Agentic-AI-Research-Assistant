"""Live updates: an in-process event bus per session, and the Server-Sent Events text format.

Two event types reach the browser:
- `snapshot`: the whole session (minus page text), sent on connect and after every step or command;
- `log`: one new action-log entry, sent the moment it's written.

Because every connection starts with a snapshot, a browser that reconnects simply gets the current
state again; nothing needs to be replayed.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from app.models import ResearchSession

EventType = Literal["snapshot", "log"]


@dataclass(frozen=True)
class ServerEvent:
    type: EventType
    data: dict[str, Any]


def session_view(session: ResearchSession) -> dict[str, Any]:
    """The session as JSON for the browser. Full page text is left out: it can be ~20 KB per
    source and the UI only needs snippets."""
    return session.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}})


class EventBus:
    """Fan-out: every subscriber (open browser tab) gets its own queue."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[ServerEvent]] = set()

    def publish(self, event: ServerEvent) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)

    def publish_snapshot(self, session: ResearchSession) -> None:
        self.publish(ServerEvent(type="snapshot", data=session_view(session)))

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[ServerEvent]]:
        queue: asyncio.Queue[ServerEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def format_sse(event: ServerEvent) -> str:
    """One SSE message: `event:` names it, `data:` holds one line of JSON, a blank line ends it."""
    return f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"


KEEPALIVE = ": keepalive\n\n"  # an SSE comment; stops proxies closing an idle connection
