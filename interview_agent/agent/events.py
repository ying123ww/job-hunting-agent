from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _empty_meta() -> dict[str, str]:
    return {}


def _empty_evidence() -> list[dict[str, Any]]:
    return []


def _empty_dimensions() -> list[str]:
    return []


@dataclass
class BeforeTurnEvent:
    user_id: str
    message: str
    requested_jd_id: str | None = None
    current_jd_id: str | None = None
    memory_now: dict[str, str] = field(default_factory=_empty_meta)
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class BeforeReasoningEvent:
    user_id: str
    message: str
    intent: str
    current_jd_id: str | None = None
    retrieved_memory_block: str = ""
    evidence_count: int = 0
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class AfterReasoningEvent:
    user_id: str
    message: str
    intent: str
    reply: str
    current_jd_id: str | None = None
    generated_plan_id: str | None = None
    top_gap_dimensions: list[str] = field(default_factory=_empty_dimensions)
    pending_memory: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class TurnCommittedEvent:
    turn_id: str
    user_id: str
    message: str
    reply: str
    intent: str
    current_jd_id: str | None
    generated_plan_id: str | None
    top_gap_dimensions: list[str] = field(default_factory=_empty_dimensions)
    pending_memory: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=_empty_evidence)
    timestamp: datetime = field(default_factory=_utcnow)
