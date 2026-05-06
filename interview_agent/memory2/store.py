from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from interview_agent.storage.repositories import InterviewRepository
from interview_agent.storage.vector_store import ChromaVectorStore


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def content_hash(summary: str, memory_type: str) -> str:
    normalized = " ".join(summary.lower().split()) + "::" + memory_type
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


class SemanticMemoryStore:
    def __init__(
        self,
        *,
        repository: InterviewRepository,
        vector_store: ChromaVectorStore,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store

    def upsert_memory(
        self,
        session: Session,
        *,
        user_id: str,
        memory_type: str,
        summary: str,
        emotional_weight: int = 0,
        extra_json: dict[str, Any] | None = None,
        source_ref: str | None = None,
        happened_at: datetime | None = None,
    ):
        hash_value = content_hash(summary, memory_type)
        existing = self.repository.find_memory_item_by_hash(
            session,
            user_id=user_id,
            memory_type=memory_type,
            content_hash=hash_value,
        )
        if existing is not None:
            return self.repository.reinforce_memory_item(
                session,
                item_id=existing.id,
                extra_json=extra_json,
                happened_at=happened_at,
            ), "reinforced"

        item = self.repository.create_memory_item(
            session,
            user_id=user_id,
            memory_type=memory_type,
            summary=summary,
            content_hash=hash_value,
            emotional_weight=emotional_weight,
            extra_json=extra_json or {},
            source_ref=source_ref,
            happened_at=happened_at,
            vector_id=None,
        )
        item.vector_id = item.id
        self.vector_store.upsert(
            collection_name="episodic_memory",
            ids=[item.id],
            texts=[summary],
            metadatas=[
                {
                    "user_id": user_id,
                    "source_type": "memory2",
                    "document_id": source_ref or "",
                    "chunk_id": item.id,
                    "question_id": "",
                    "dimension": str((extra_json or {}).get("dimension", "")),
                    "topics_text": str((extra_json or {}).get("topics_text", "")),
                    "is_active": True,
                    "memory_type": memory_type,
                }
            ],
        )
        return item, "created"

    def list_recent_memory(self, session: Session, *, user_id: str, limit: int = 20):
        return self.repository.list_memory_items(session, user_id=user_id, limit=limit)

    def get_memory_items(self, session: Session, *, ids: list[str]):
        return self.repository.list_memory_items_by_ids(session, ids=ids)
