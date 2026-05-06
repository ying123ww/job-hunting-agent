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


def _empty_strings() -> list[str]:
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
    semantic_memory_block: str = ""
    evidence_count: int = 0
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class BeforeStepEvent:
    user_id: str
    message: str
    intent: str
    iteration: int
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    planned_tools: list[str] = field(default_factory=_empty_strings)
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class AfterStepEvent:
    user_id: str
    message: str
    intent: str
    iteration: int
    tool_name: str = ""
    status: str = "ok"
    result_preview: str = ""
    tools_called: list[str] = field(default_factory=_empty_strings)
    has_more: bool = False
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ToolCallStartedEvent:
    user_id: str
    message: str
    intent: str
    iteration: int
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ToolCallCompletedEvent:
    user_id: str
    message: str
    intent: str
    iteration: int
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    result_preview: str = ""
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


@dataclass
class ProactiveTickStartedEvent:
    tick_id: str
    user_id: str
    current_jd_id: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass
class ProactiveDriftStartedEvent:
    tick_id: str
    user_id: str
    current_jd_id: str | None = None
    recent_context: str = ""
    semantic_memory_block: str = ""
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ProactiveDriftCompletedEvent:
    tick_id: str
    user_id: str
    message: str
    current_jd_id: str | None = None
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class ProactiveTickCompletedEvent:
    tick_id: str
    user_id: str
    action: str
    message: str
    current_jd_id: str | None = None
    generated_plan_id: str | None = None
    drift_entered: bool = False
    timestamp: datetime = field(default_factory=_utcnow)
