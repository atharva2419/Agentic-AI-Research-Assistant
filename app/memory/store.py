"""Where memory items are kept: SQL (real) or in memory (tests and runs without a database).

Expiry is enforced in the queries (`expires_at > now`), so an expired memory is never used even
if the purge job hasn't run yet. `purge_expired()` then deletes them for good (at startup).
"""

from datetime import datetime
from typing import Protocol

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.models import MemoryItem
from app.storage.db import MemoryRow, as_utc


class MemoryStore(Protocol):
    def save(self, item: MemoryItem) -> None: ...

    def list_items(self, user_id: str, now: datetime) -> list[MemoryItem]: ...

    def delete(self, user_id: str, item_id: str) -> bool: ...

    def delete_for_session(self, session_id: str) -> None: ...

    def purge_expired(self, now: datetime) -> int: ...


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}  # by session ID: one memory per session

    def save(self, item: MemoryItem) -> None:
        previous = self._items.get(item.session_id)
        if previous is not None:
            item = item.model_copy(update={"id": previous.id})
        self._items[item.session_id] = item

    def list_items(self, user_id: str, now: datetime) -> list[MemoryItem]:
        items = [i for i in self._items.values() if i.user_id == user_id and i.expires_at > now]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def delete(self, user_id: str, item_id: str) -> bool:
        for key, item in self._items.items():
            if item.id == item_id and item.user_id == user_id:
                del self._items[key]
                return True
        return False

    def delete_for_session(self, session_id: str) -> None:
        self._items.pop(session_id, None)

    def purge_expired(self, now: datetime) -> int:
        expired = [k for k, i in self._items.items() if i.expires_at <= now]
        for key in expired:
            del self._items[key]
        return len(expired)


def _to_item(row: MemoryRow) -> MemoryItem:
    return MemoryItem(
        id=row.id,
        user_id=row.user_id,
        session_id=row.session_id,
        topic=row.topic,
        summary=row.summary,
        key_findings=row.key_findings,
        source_urls=row.source_urls,
        suggested_topics=row.suggested_topics,
        created_at=as_utc(row.created_at),
        expires_at=as_utc(row.expires_at),
    )


class SqlMemoryStore:
    def __init__(self, engine: Engine) -> None:
        self._db = sessionmaker(engine, expire_on_commit=False)

    def save(self, item: MemoryItem) -> None:
        """Upsert by session: a rewritten report replaces that session's memory."""
        with self._db.begin() as db:
            row = db.scalar(select(MemoryRow).where(MemoryRow.session_id == item.session_id))
            if row is None:
                row = MemoryRow(id=item.id, session_id=item.session_id)
                db.add(row)
            row.user_id = item.user_id
            row.topic = item.topic
            row.summary = item.summary
            row.key_findings = item.key_findings
            row.source_urls = item.source_urls
            row.suggested_topics = item.suggested_topics
            row.created_at = item.created_at
            row.expires_at = item.expires_at

    def list_items(self, user_id: str, now: datetime) -> list[MemoryItem]:
        query = (
            select(MemoryRow)
            .where(MemoryRow.user_id == user_id, MemoryRow.expires_at > now)
            .order_by(MemoryRow.created_at.desc())
        )
        with self._db() as db:
            return [_to_item(row) for row in db.scalars(query)]

    def delete(self, user_id: str, item_id: str) -> bool:
        with self._db.begin() as db:
            result = db.execute(
                delete(MemoryRow).where(MemoryRow.id == item_id, MemoryRow.user_id == user_id)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    def delete_for_session(self, session_id: str) -> None:
        with self._db.begin() as db:
            db.execute(delete(MemoryRow).where(MemoryRow.session_id == session_id))

    def purge_expired(self, now: datetime) -> int:
        with self._db.begin() as db:
            result = db.execute(delete(MemoryRow).where(MemoryRow.expires_at <= now))
            return int(result.rowcount)  # type: ignore[attr-defined]
