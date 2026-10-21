"""SessionRunner: drives sessions in the background for the API.

It is the web equivalent of the CLI loop. One asyncio task per session calls `orchestrator.step()`
until the session finishes or needs the user; then it sleeps until a command wakes it up.

Concurrency rules (all on one event loop, so no threads):
- A per-session lock is held while a step runs. Commands that change research state (answer,
  approve, ...) take the same lock, so they apply between steps, never in the middle of one.
- Pause and resume only flip a flag, so they skip the lock and take effect after the current step.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from app.api.events import EventBus, ServerEvent
from app.api.store import SessionStore
from app.models import (
    Actor,
    Pause,
    ResearchSession,
    Resume,
    Status,
    UserCommand,
    utc_now,
)
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.state_machine import TERMINAL, is_runnable

logger = logging.getLogger(__name__)


class SessionNotFound(Exception):
    pass


@dataclass
class SessionHandle:
    session: ResearchSession
    bus: EventBus = field(default_factory=EventBus)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wakeup: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class SessionRunner:
    def __init__(self, orchestrator: Orchestrator, store: SessionStore) -> None:
        self.orchestrator = orchestrator
        self.store = store
        self._handles: dict[str, SessionHandle] = {}

    # --- Public API used by the routes ---------------------------------------------------------

    def start(self, session: ResearchSession) -> SessionHandle:
        handle = SessionHandle(session=session)
        session.set_log_listener(
            lambda entry: handle.bus.publish(
                ServerEvent(type="log", data=entry.model_dump(mode="json"))
            )
        )
        self._handles[session.id] = handle
        self.store.save(session)
        handle.task = asyncio.create_task(self._drive(handle), name=f"session-{session.id}")
        return handle

    def get(self, session_id: str) -> SessionHandle:
        handle = self._handles.get(session_id)
        if handle is None:
            raise SessionNotFound(session_id)
        return handle

    async def submit(self, session_id: str, command: UserCommand) -> ResearchSession:
        """Apply a user command. Raises CommandRejected (from the orchestrator) if it doesn't
        fit the session's current state; the route turns that into HTTP 409."""
        handle = self.get(session_id)
        if isinstance(command, Pause | Resume):
            await self.orchestrator.handle_command(handle.session, command)
        else:
            async with handle.lock:
                await self.orchestrator.handle_command(handle.session, command)
        self._after_change(handle)
        handle.wakeup.set()
        return handle.session

    async def shutdown(self) -> None:
        tasks = [h.task for h in self._handles.values() if h.task and not h.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- The background loop -------------------------------------------------------------------

    async def _drive(self, handle: SessionHandle) -> None:
        session = handle.session
        while session.status not in TERMINAL:
            # Clear before checking, so a command that arrives in between still wakes us.
            handle.wakeup.clear()
            if is_runnable(session.status, session.paused):
                async with handle.lock:
                    await self._safe_step(session)
                self._after_change(handle)
            else:
                await handle.wakeup.wait()

    async def _safe_step(self, session: ResearchSession) -> None:
        """The orchestrator already turns LLM failures into a FAILED session. This catches bugs,
        so one broken session can't crash the server or hang its browser tab."""
        try:
            await self.orchestrator.step(session)
        except Exception as exc:
            logger.exception("session %s crashed", session.id)
            session.error = f"internal error: {exc}"
            session.add_log(
                actor=Actor.SYSTEM,
                step=session.status.value,
                action="internal error",
                decision="session stopped",
                reason=str(exc),
            )
            session.status = Status.FAILED
            session.updated_at = utc_now()

    def _after_change(self, handle: SessionHandle) -> None:
        self.store.save(handle.session)
        handle.bus.publish_snapshot(handle.session)
