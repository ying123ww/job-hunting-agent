from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from interview_agent.memory2.models import MemoryWriteResult
from interview_agent.memory2.store import SemanticMemoryStore


_PENDING_LINE = re.compile(r"^- \[(?P<tag>[^\]]+)\] (?P<content>.+)$")

_TAG_TO_MEMORY_TYPE = {
    "requested_memory": "event",
    "identity": "profile",
    "preference": "preference",
    "correction": "profile",
    "key_info": "profile",
}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SemanticMemorizer:
    def __init__(self, *, store: SemanticMemoryStore) -> None:
        self.store = store

    def memorize_pending(
        self,
        session: Session,
        *,
        user_id: str,
        pending_text: str,
        source_ref: str,
    ) -> list[MemoryWriteResult]:
        results: list[MemoryWriteResult] = []
        for raw_line in pending_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _PENDING_LINE.match(line)
            if match:
                tag = match.group("tag").strip().lower()
                content = match.group("content").strip()
            else:
                tag = "event"
                content = line.lstrip("- ").strip()
            memory_type = _TAG_TO_MEMORY_TYPE.get(tag, "event")
            item, action = self.store.upsert_memory(
                session,
                user_id=user_id,
                memory_type=memory_type,
                summary=content,
                extra_json={"tag": tag},
                source_ref=source_ref,
                happened_at=utcnow(),
            )
            results.append(
                MemoryWriteResult(
                    item_id=item.id,
                    action=action,
                    memory_type=item.memory_type,
                    summary=item.summary,
                )
            )
        return results

    def memorize_turn_summary(
        self,
        session: Session,
        *,
        user_id: str,
        summary: str,
        source_ref: str,
        extra_json: dict[str, object] | None = None,
    ) -> MemoryWriteResult:
        item, action = self.store.upsert_memory(
            session,
            user_id=user_id,
            memory_type="event",
            summary=summary,
            extra_json=dict(extra_json or {}),
            source_ref=source_ref,
            happened_at=utcnow(),
        )
        return MemoryWriteResult(
            item_id=item.id,
            action=action,
            memory_type=item.memory_type,
            summary=item.summary,
        )
