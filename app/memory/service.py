"""Long-term memory: remember finished research, recall it for related topics, suggest new ones.

All code, no LLM calls. Recalled memories reach the agent through the shared prompt context,
labeled "from past research", so the planner builds on them instead of repeating them. The report
lists them separately (built by code), never as citations, because citations must point at sources
collected in the current session.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from app.blueprint import MemoryConfig
from app.memory.retrieval import Retriever, TfidfRetriever, tokenize
from app.memory.store import MemoryStore
from app.models import MemoryItem, MemoryMatch, ResearchSession, utc_now

MAX_FINDINGS = 6


def _document(item: MemoryItem) -> str:
    # The topic is repeated so it weighs more than the longer summary text.
    return " ".join([item.topic, item.topic, item.summary, *item.key_findings])


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        config: MemoryConfig,
        retriever: Retriever | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.config = config
        self.retriever = retriever or TfidfRetriever()
        self.clock = clock

    def remember(self, session: ResearchSession) -> MemoryItem | None:
        """Save what a finished session found. Only supported (verified-citation) statements are
        remembered, with the URLs of the sources they cite."""
        report = session.report
        if report is None:
            return None
        statements = [*report.key_takeaways, *(c for s in report.sections for c in s.statements)]
        supported = [s for s in statements if s.supported]
        cited = {sid for s in supported for sid in s.source_ids}
        now = self.clock()
        item = MemoryItem(
            user_id=session.user_id,
            session_id=session.id,
            topic=session.topic,
            summary=report.executive_summary,
            key_findings=[s.text for s in supported[:MAX_FINDINGS]],
            source_urls=[s.url for s in session.sources if s.id in cited],
            suggested_topics=report.suggested_next_topics,
            created_at=now,
            expires_at=now + timedelta(days=self.config.ttl_days),
        )
        self.store.save(item)
        return item

    def recall(
        self, user_id: str, topic: str, exclude_session_id: str | None = None
    ) -> list[MemoryMatch]:
        """The user's past sessions most related to `topic`.

        Similarity must pass `min_similarity`; ranking then favors newer memories: the weight goes
        from 1.0 (just researched) down to 0.5 (about to expire), so a fresh, slightly less similar
        memory can outrank a stale one.
        """
        if self.config.recall_top_k == 0:
            return []
        now = self.clock()
        items = [
            i for i in self.store.list_items(user_id, now) if i.session_id != exclude_session_id
        ]
        scores = self.retriever.similarities(topic, [_document(i) for i in items])
        ttl = self.config.ttl_days
        ranked = []
        for item, similarity in zip(items, scores, strict=True):
            if similarity < self.config.min_similarity:
                continue
            age_days = (now - item.created_at).days
            weight = 1 - 0.5 * min(age_days / ttl, 1.0)
            ranked.append((similarity * weight, similarity, item))
        ranked.sort(key=lambda r: r[0], reverse=True)
        return [
            MemoryMatch(
                session_id=item.session_id,
                topic=item.topic,
                summary=item.summary,
                key_findings=item.key_findings,
                similarity=round(similarity, 3),
                created_at=item.created_at,
            )
            for _, similarity, item in ranked[: self.config.recall_top_k]
        ]

    def suggestions(self, user_id: str) -> list[str]:
        """Next topics proposed by past reports, newest first, minus topics already researched.

        A suggestion counts as researched only if it adds no new words to a past topic
        ("AI in journalism" is skipped, "Regulation of AI in journalism" is not). Similarity would
        be the wrong test here: good follow-up topics naturally share the original topic's words.
        """
        items = self.store.list_items(user_id, self.clock())
        researched = [set(tokenize(i.topic)) for i in items]
        suggestions: list[str] = []
        seen: set[frozenset[str]] = set()
        for item in items:
            for topic in item.suggested_topics:
                words = frozenset(tokenize(topic))
                if not words or words in seen or any(words <= past for past in researched):
                    continue
                seen.add(words)
                suggestions.append(topic.strip())
                if len(suggestions) >= self.config.max_suggestions:
                    return suggestions
        return suggestions

    def list_items(self, user_id: str) -> list[MemoryItem]:
        return self.store.list_items(user_id, self.clock())

    def forget(self, user_id: str, item_id: str) -> bool:
        return self.store.delete(user_id, item_id)

    def forget_session(self, session_id: str) -> None:
        self.store.delete_for_session(session_id)

    def purge_expired(self) -> int:
        return self.store.purge_expired(self.clock())
