from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MemoryHit:
    id: str
    memory_type: str
    summary: str
    score: float
    reinforcement: int
    happened_at: datetime | None = None
    source_ref: str | None = None
    extra_json: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryWriteResult:
    item_id: str
    action: str
    memory_type: str
    summary: str
