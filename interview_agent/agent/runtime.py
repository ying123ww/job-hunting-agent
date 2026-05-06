from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import (
    AfterReasoningEvent,
    BeforeReasoningEvent,
    BeforeTurnEvent,
    TurnCommittedEvent,
)
from interview_agent.agent.lifecycle import Phase, PhaseFrame
from interview_agent.agent.memory import AgentMemoryStore, MemorySnapshot
from interview_agent.agent.reasoner import AgentReasoner, AgentTurnDecision
from interview_agent.retrieval.service import EvidenceItem
from interview_agent.storage.models import make_id
from interview_agent.storage.repositories import InterviewRepository


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _empty_trace() -> list[str]:
    return []


@dataclass(slots=True)
class AgentTurnRequest:
    user_id: str
    message: str
    jd_id: str | None = None


@dataclass(slots=True)
class AgentTurnResponse:
    turn_id: str
    intent: str
    reply: str
    current_jd_id: str | None
    generated_plan_id: str | None
    evidence: list[EvidenceItem]
    lifecycle: list[str] = field(default_factory=_empty_trace)
    memory_now: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class BeforeTurnInput:
    request: AgentTurnRequest


@dataclass(slots=True)
class BeforeTurnContext:
    user_id: str
    message: str
    current_jd_id: str | None
    memory_snapshot: MemorySnapshot
    lifecycle: list[str]


@dataclass(slots=True)
class BeforeTurnFrame(PhaseFrame[BeforeTurnInput, BeforeTurnContext]):
    pass


@dataclass(slots=True)
class BeforeReasoningInput:
    before_turn: BeforeTurnContext


@dataclass(slots=True)
class BeforeReasoningContext:
    user_id: str
    message: str
    current_jd_id: str | None
    memory_snapshot: MemorySnapshot
    intent: str
    lifecycle: list[str]


@dataclass(slots=True)
class BeforeReasoningFrame(PhaseFrame[BeforeReasoningInput, BeforeReasoningContext]):
    pass


@dataclass(slots=True)
class AfterReasoningInput:
    before_reasoning: BeforeReasoningContext
    decision: AgentTurnDecision


@dataclass(slots=True)
class AfterReasoningContext:
    turn_id: str
    user_id: str
    message: str
    current_jd_id: str | None
    decision: AgentTurnDecision
    lifecycle: list[str]


@dataclass(slots=True)
class AfterReasoningFrame(PhaseFrame[AfterReasoningInput, AfterReasoningContext]):
    pass


@dataclass(slots=True)
class AfterTurnInput:
    after_reasoning: AfterReasoningContext


@dataclass(slots=True)
class AfterTurnFrame(PhaseFrame[AfterTurnInput, AgentTurnResponse]):
    pass


class _LoadMemoryModule:
    def __init__(self, memory_store: AgentMemoryStore, repository: InterviewRepository) -> None:
        self.memory_store = memory_store
        self.repository = repository

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        request = frame.input.request
        memory_snapshot = self.memory_store.snapshot()
        lifecycle = ["BeforeTurn"]
        current_jd_id = request.jd_id or memory_snapshot.now_state.get("current_jd_id") or None
        frame.slots["memory_snapshot"] = memory_snapshot
        frame.slots["current_jd_id"] = current_jd_id
        frame.slots["lifecycle"] = lifecycle
        return frame


class _EmitBeforeTurnModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        request = frame.input.request
        event = BeforeTurnEvent(
            user_id=request.user_id,
            message=request.message,
            requested_jd_id=request.jd_id,
            current_jd_id=frame.slots["current_jd_id"],
            memory_now=frame.slots["memory_snapshot"].now_state,
        )
        event = await self.event_bus.emit(event)
        frame.slots["current_jd_id"] = event.current_jd_id
        return frame


class _ReturnBeforeTurnModule:
    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        request = frame.input.request
        frame.output = BeforeTurnContext(
            user_id=request.user_id,
            message=request.message,
            current_jd_id=frame.slots["current_jd_id"],
            memory_snapshot=frame.slots["memory_snapshot"],
            lifecycle=list(frame.slots["lifecycle"]),
        )
        return frame


class _DetectIntentModule:
    def __init__(self, reasoner: AgentReasoner) -> None:
        self.reasoner = reasoner

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        intent = self.reasoner.detect_intent(frame.input.before_turn.message)
        frame.slots["intent"] = intent
        lifecycle = list(frame.input.before_turn.lifecycle)
        lifecycle.append("BeforeReasoning")
        frame.slots["lifecycle"] = lifecycle
        return frame


class _EmitBeforeReasoningModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        snapshot = frame.input.before_turn.memory_snapshot
        event = BeforeReasoningEvent(
            user_id=frame.input.before_turn.user_id,
            message=frame.input.before_turn.message,
            intent=frame.slots["intent"],
            current_jd_id=frame.input.before_turn.current_jd_id,
            retrieved_memory_block=snapshot.recent_context,
        )
        event = await self.event_bus.emit(event)
        frame.slots["intent"] = event.intent
        return frame


class _ReturnBeforeReasoningModule:
    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        before_turn = frame.input.before_turn
        frame.output = BeforeReasoningContext(
            user_id=before_turn.user_id,
            message=before_turn.message,
            current_jd_id=before_turn.current_jd_id,
            memory_snapshot=before_turn.memory_snapshot,
            intent=frame.slots["intent"],
            lifecycle=list(frame.slots["lifecycle"]),
        )
        return frame


class _AssignTurnIdModule:
    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        frame.slots["turn_id"] = make_id("turn")
        lifecycle = list(frame.input.before_reasoning.lifecycle)
        lifecycle.append("AfterReasoning")
        frame.slots["lifecycle"] = lifecycle
        return frame


class _EmitAfterReasoningModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        before_reasoning = frame.input.before_reasoning
        decision = frame.input.decision
        event = AfterReasoningEvent(
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            intent=decision.intent,
            reply=decision.reply,
            current_jd_id=before_reasoning.current_jd_id,
            generated_plan_id=decision.generated_plan_id,
            top_gap_dimensions=decision.top_gap_dimensions,
            pending_memory=decision.pending_memory,
        )
        event = await self.event_bus.emit(event)
        frame.input.decision.reply = event.reply
        frame.input.decision.pending_memory = event.pending_memory
        return frame


class _ReturnAfterReasoningModule:
    async def run(self, frame: AfterReasoningFrame) -> AfterReasoningFrame:
        before_reasoning = frame.input.before_reasoning
        frame.output = AfterReasoningContext(
            turn_id=frame.slots["turn_id"],
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            current_jd_id=before_reasoning.current_jd_id,
            decision=frame.input.decision,
            lifecycle=list(frame.slots["lifecycle"]),
        )
        return frame


class _CommitTurnModule:
    def __init__(self, event_bus: EventBus, memory_store: AgentMemoryStore) -> None:
        self.event_bus = event_bus
        self.memory_store = memory_store

    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        after_reasoning = frame.input.after_reasoning
        lifecycle = list(after_reasoning.lifecycle)
        lifecycle.append("AfterTurn")
        frame.slots["lifecycle"] = lifecycle
        event = TurnCommittedEvent(
            turn_id=after_reasoning.turn_id,
            user_id=after_reasoning.user_id,
            message=after_reasoning.message,
            reply=after_reasoning.decision.reply,
            intent=after_reasoning.decision.intent,
            current_jd_id=after_reasoning.current_jd_id,
            generated_plan_id=after_reasoning.decision.generated_plan_id,
            top_gap_dimensions=after_reasoning.decision.top_gap_dimensions,
            pending_memory=after_reasoning.decision.pending_memory,
            evidence=[
                {
                    "source_type": item.source_type,
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                    "text": item.text,
                    "score": item.score,
                    "metadata_summary": item.metadata_summary,
                }
                for item in after_reasoning.decision.evidence
            ],
            timestamp=_utcnow(),
        )
        self.event_bus.enqueue(event)
        await self.event_bus.drain()
        frame.slots["memory_now"] = self.memory_store.read_now_state()
        return frame


class _ReturnAfterTurnModule:
    async def run(self, frame: AfterTurnFrame) -> AfterTurnFrame:
        after_reasoning = frame.input.after_reasoning
        frame.output = AgentTurnResponse(
            turn_id=after_reasoning.turn_id,
            intent=after_reasoning.decision.intent,
            reply=after_reasoning.decision.reply,
            current_jd_id=after_reasoning.current_jd_id,
            generated_plan_id=after_reasoning.decision.generated_plan_id,
            evidence=after_reasoning.decision.evidence,
            lifecycle=list(frame.slots["lifecycle"]),
            memory_now=dict(frame.slots["memory_now"]),
        )
        return frame


class InterviewAgentRuntime:
    def __init__(
        self,
        *,
        repository: InterviewRepository,
        reasoner: AgentReasoner,
        memory_store: AgentMemoryStore,
        event_bus: EventBus,
    ) -> None:
        self.repository = repository
        self.reasoner = reasoner
        self.memory_store = memory_store
        self.event_bus = event_bus
        self._before_turn = Phase(
            [_LoadMemoryModule(memory_store, repository), _EmitBeforeTurnModule(event_bus), _ReturnBeforeTurnModule()],
            frame_factory=BeforeTurnFrame,
        )
        self._before_reasoning = Phase(
            [_DetectIntentModule(reasoner), _EmitBeforeReasoningModule(event_bus), _ReturnBeforeReasoningModule()],
            frame_factory=BeforeReasoningFrame,
        )
        self._after_reasoning = Phase(
            [_AssignTurnIdModule(), _EmitAfterReasoningModule(event_bus), _ReturnAfterReasoningModule()],
            frame_factory=AfterReasoningFrame,
        )
        self._after_turn = Phase(
            [_CommitTurnModule(event_bus, memory_store), _ReturnAfterTurnModule()],
            frame_factory=AfterTurnFrame,
        )

    async def run_turn(self, session: Session, request: AgentTurnRequest) -> AgentTurnResponse:
        before_turn = await self._before_turn.run(BeforeTurnInput(request=request))
        before_reasoning = await self._before_reasoning.run(BeforeReasoningInput(before_turn=before_turn))
        decision = self.reasoner.run_turn(
            session,
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            current_jd_id=before_reasoning.current_jd_id,
            memory_snapshot=before_reasoning.memory_snapshot,
        )
        after_reasoning = await self._after_reasoning.run(
            AfterReasoningInput(before_reasoning=before_reasoning, decision=decision)
        )
        return await self._after_turn.run(AfterTurnInput(after_reasoning=after_reasoning))
