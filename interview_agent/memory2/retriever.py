from __future__ import annotations

from sqlalchemy.orm import Session

from interview_agent.memory2.models import MemoryHit
from interview_agent.memory2.query_rewriter import rewrite_query
from interview_agent.memory2.store import SemanticMemoryStore
from interview_agent.storage.vector_store import ChromaVectorStore


class SemanticMemoryRetriever:
    def __init__(
        self,
        *,
        store: SemanticMemoryStore,
        vector_store: ChromaVectorStore,
    ) -> None:
        self.store = store
        self.vector_store = vector_store

    def retrieve(
        self,
        session: Session,
        *,
        user_id: str,
        query: str,
        memory_types: list[str] | None = None,
        limit: int = 5,
    ) -> list[MemoryHit]:
        seen: dict[str, float] = {}
        for lane in rewrite_query(query):
            matches = self.vector_store.query(
                collection_name="episodic_memory",
                query_text=lane,
                where={"user_id": user_id, "is_active": True},
                limit=limit,
            )
            for match in matches:
                if memory_types and match.metadata.get("memory_type") not in memory_types:
                    continue
                current = seen.get(match.vector_id, 0.0)
                seen[match.vector_id] = max(current, match.score)
        items = self.store.get_memory_items(session, ids=list(seen.keys()))
        item_map = {item.id: item for item in items}
        hits: list[MemoryHit] = []
        for item_id, score in sorted(seen.items(), key=lambda pair: pair[1], reverse=True):
            item = item_map.get(item_id)
            if item is None:
                continue
            hits.append(
                MemoryHit(
                    id=item.id,
                    memory_type=item.memory_type,
                    summary=item.summary,
                    score=round(score + min(item.reinforcement * 0.02, 0.2), 4),
                    reinforcement=item.reinforcement,
                    happened_at=item.happened_at,
                    source_ref=item.source_ref,
                    extra_json=item.extra_json,
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:limit]
