from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import (
    AfterReasoningEvent,
    AfterStepEvent,
    BeforeReasoningEvent,
    BeforeStepEvent,
    BeforeTurnEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    TurnCommittedEvent,
)
from interview_agent.agent.lifecycle import Phase, PhaseFrame
from interview_agent.agent.memory import AgentMemoryStore, MemorySnapshot
from interview_agent.agent.plugins import PluginManager
from interview_agent.agent.reasoner import AgentReasoner, AgentTurnDecision
from interview_agent.agent.tools import ToolCall, ToolExecutionContext, ToolRegistry, ToolResult
from interview_agent.retrieval.service import EvidenceItem
from interview_agent.storage.models import make_id


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
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass(slots=True)
class BeforeTurnInput:
    session: Session
    request: AgentTurnRequest


@dataclass(slots=True)
class BeforeTurnContext:
    session: Session
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
    session: Session
    user_id: str
    message: str
    current_jd_id: str | None
    memory_snapshot: MemorySnapshot
    intent: str
    semantic_memory_block: str
    lifecycle: list[str]


@dataclass(slots=True)
class BeforeReasoningFrame(PhaseFrame[BeforeReasoningInput, BeforeReasoningContext]):
    pass


@dataclass(slots=True)
class BeforeStepInput:
    before_reasoning: BeforeReasoningContext
    iteration: int
    tool_call: ToolCall
    previous_results: list[ToolResult]


@dataclass(slots=True)
class BeforeStepContext:
    session: Session
    user_id: str
    message: str
    intent: str
    current_jd_id: str | None
    iteration: int
    tool_call: ToolCall
    previous_results: list[ToolResult]


@dataclass(slots=True)
class BeforeStepFrame(PhaseFrame[BeforeStepInput, BeforeStepContext]):
    pass


@dataclass(slots=True)
class AfterStepInput:
    before_step: BeforeStepContext
    result: ToolResult
    has_more: bool


@dataclass(slots=True)
class AfterStepContext:
    iteration: int
    tool_call: ToolCall
    result: ToolResult
    has_more: bool


@dataclass(slots=True)
class AfterStepFrame(PhaseFrame[AfterStepInput, AfterStepContext]):
    pass


@dataclass(slots=True)
class AfterReasoningInput:
    before_reasoning: BeforeReasoningContext
    decision: AgentTurnDecision


@dataclass(slots=True)
class AfterReasoningContext:
    session: Session
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
    def __init__(self, memory_store: AgentMemoryStore) -> None:
        self.memory_store = memory_store

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
            session=frame.input.session,
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
        before_turn = frame.input.before_turn
        event = BeforeReasoningEvent(
            user_id=before_turn.user_id,
            message=before_turn.message,
            intent=frame.slots["intent"],
            current_jd_id=before_turn.current_jd_id,
            retrieved_memory_block=before_turn.memory_snapshot.recent_context,
            semantic_memory_block=str(frame.slots.get("memory2:block", "")),
        )
        event = await self.event_bus.emit(event)
        frame.slots["intent"] = event.intent
        frame.slots["memory2:block"] = event.semantic_memory_block
        return frame


class _ReturnBeforeReasoningModule:
    async def run(self, frame: BeforeReasoningFrame) -> BeforeReasoningFrame:
        before_turn = frame.input.before_turn
        frame.output = BeforeReasoningContext(
            session=before_turn.session,
            user_id=before_turn.user_id,
            message=before_turn.message,
            current_jd_id=before_turn.current_jd_id,
            memory_snapshot=before_turn.memory_snapshot,
            intent=frame.slots["intent"],
            semantic_memory_block=str(frame.slots.get("memory2:block", "")),
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
            session=before_reasoning.session,
            turn_id=frame.slots["turn_id"],
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            current_jd_id=before_reasoning.current_jd_id,
            decision=frame.input.decision,
            lifecycle=list(frame.slots["lifecycle"]),
        )
        return frame


class _PrepareBeforeStepModule:
    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        frame.slots["tool_call"] = ToolCall(
            tool_name=frame.input.tool_call.tool_name,
            arguments=dict(frame.input.tool_call.arguments),
        )
        return frame


class _EmitBeforeStepModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        before_reasoning = frame.input.before_reasoning
        tool_call: ToolCall = frame.slots["tool_call"]
        event = BeforeStepEvent(
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            intent=before_reasoning.intent,
            iteration=frame.input.iteration,
            tool_name=tool_call.tool_name,
            arguments=dict(tool_call.arguments),
            planned_tools=[tool_call.tool_name],
        )
        await self.event_bus.emit(event)
        return frame


class _ReturnBeforeStepModule:
    async def run(self, frame: BeforeStepFrame) -> BeforeStepFrame:
        before_reasoning = frame.input.before_reasoning
        frame.output = BeforeStepContext(
            session=before_reasoning.session,
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            intent=before_reasoning.intent,
            current_jd_id=before_reasoning.current_jd_id,
            iteration=frame.input.iteration,
            tool_call=frame.slots["tool_call"],
            previous_results=list(frame.input.previous_results),
        )
        return frame


class _EmitAfterStepModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        before_step = frame.input.before_step
        await self.event_bus.fanout(
            AfterStepEvent(
                user_id=before_step.user_id,
                message=before_step.message,
                intent=before_step.intent,
                iteration=before_step.iteration,
                tool_name=before_step.tool_call.tool_name,
                status=frame.input.result.status,
                result_preview=frame.input.result.preview,
                tools_called=[before_step.tool_call.tool_name],
                has_more=frame.input.has_more,
            )
        )
        return frame


class _ReturnAfterStepModule:
    async def run(self, frame: AfterStepFrame) -> AfterStepFrame:
        frame.output = AfterStepContext(
            iteration=frame.input.before_step.iteration,
            tool_call=frame.input.before_step.tool_call,
            result=frame.input.result,
            has_more=frame.input.has_more,
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
            tool_results=list(after_reasoning.decision.tool_results),
        )
        return frame


class InterviewAgentRuntime:
    def __init__(
        self,
        *,
        reasoner: AgentReasoner,
        memory_store: AgentMemoryStore,
        event_bus: EventBus,
        tool_registry: ToolRegistry,
        plugin_manager: PluginManager,
    ) -> None:
        self.reasoner = reasoner
        self.memory_store = memory_store
        self.event_bus = event_bus
        self.tool_registry = tool_registry
        self.plugin_manager = plugin_manager

        self._before_turn = Phase(
            [
                *self.plugin_manager.phase_modules("before_turn_modules_early"),
                _LoadMemoryModule(memory_store),
                _EmitBeforeTurnModule(event_bus),
                *self.plugin_manager.phase_modules("before_turn_modules_late"),
                _ReturnBeforeTurnModule(),
            ],
            frame_factory=BeforeTurnFrame,
        )
        self._before_reasoning = Phase(
            [
                *self.plugin_manager.phase_modules("before_reasoning_modules_early"),
                _DetectIntentModule(reasoner),
                _EmitBeforeReasoningModule(event_bus),
                *self.plugin_manager.phase_modules("before_reasoning_modules_late"),
                _ReturnBeforeReasoningModule(),
            ],
            frame_factory=BeforeReasoningFrame,
        )
        self._after_reasoning = Phase(
            [
                *self.plugin_manager.phase_modules("after_reasoning_modules_early"),
                _AssignTurnIdModule(),
                _EmitAfterReasoningModule(event_bus),
                *self.plugin_manager.phase_modules("after_reasoning_modules_late"),
                _ReturnAfterReasoningModule(),
            ],
            frame_factory=AfterReasoningFrame,
        )
        self._before_step = Phase(
            [
                *self.plugin_manager.phase_modules("before_step_modules_early"),
                _PrepareBeforeStepModule(),
                _EmitBeforeStepModule(event_bus),
                *self.plugin_manager.phase_modules("before_step_modules_late"),
                _ReturnBeforeStepModule(),
            ],
            frame_factory=BeforeStepFrame,
        )
        self._after_step = Phase(
            [
                *self.plugin_manager.phase_modules("after_step_modules_early"),
                _EmitAfterStepModule(event_bus),
                *self.plugin_manager.phase_modules("after_step_modules_late"),
                _ReturnAfterStepModule(),
            ],
            frame_factory=AfterStepFrame,
        )
        self._after_turn = Phase(
            [
                *self.plugin_manager.phase_modules("after_turn_modules_early"),
                _CommitTurnModule(event_bus, memory_store),
                *self.plugin_manager.phase_modules("after_turn_modules_late"),
                _ReturnAfterTurnModule(),
            ],
            frame_factory=AfterTurnFrame,
        )

    async def run_turn(self, session: Session, request: AgentTurnRequest) -> AgentTurnResponse:
        before_turn = await self._before_turn.run(BeforeTurnInput(session=session, request=request))
        before_reasoning = await self._before_reasoning.run(BeforeReasoningInput(before_turn=before_turn))
        tool_calls = self.reasoner.plan_tool_calls(message=before_reasoning.message, intent=before_reasoning.intent)
        tool_results = await self._run_tool_loop(before_reasoning=before_reasoning, tool_calls=tool_calls)
        decision = self.reasoner.finalize_turn(
            session,
            user_id=before_reasoning.user_id,
            message=before_reasoning.message,
            current_jd_id=before_reasoning.current_jd_id,
            intent=before_reasoning.intent,
            memory_snapshot=before_reasoning.memory_snapshot,
            tool_results=tool_results,
        )
        after_reasoning = await self._after_reasoning.run(
            AfterReasoningInput(before_reasoning=before_reasoning, decision=decision)
        )
        return await self._after_turn.run(AfterTurnInput(after_reasoning=after_reasoning))

    async def _run_tool_loop(
        self,
        *,
        before_reasoning: BeforeReasoningContext,
        tool_calls: list[ToolCall],
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for iteration, call in enumerate(tool_calls):
            before_step = await self._before_step.run(
                BeforeStepInput(
                    before_reasoning=before_reasoning,
                    iteration=iteration,
                    tool_call=call,
                    previous_results=list(results),
                )
            )
            tool_call = before_step.tool_call
            await self.event_bus.fanout(
                ToolCallStartedEvent(
                    user_id=before_reasoning.user_id,
                    message=before_reasoning.message,
                    intent=before_reasoning.intent,
                    iteration=iteration,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                )
            )
            ctx = ToolExecutionContext(
                session=before_reasoning.session,
                user_id=before_reasoning.user_id,
                current_jd_id=before_reasoning.current_jd_id,
                message=before_reasoning.message,
            )
            try:
                tool = self.tool_registry.get(tool_call.tool_name)
                result = tool.run(ctx, tool_call.arguments)
            except Exception as exc:
                result = ToolResult(
                    tool_name=tool_call.tool_name,
                    status="error",
                    payload={"error": str(exc)},
                    preview=f"tool error: {exc}",
                )
            await self.event_bus.fanout(
                ToolCallCompletedEvent(
                    user_id=before_reasoning.user_id,
                    message=before_reasoning.message,
                    intent=before_reasoning.intent,
                    iteration=iteration,
                    tool_name=tool_call.tool_name,
                    arguments=tool_call.arguments,
                    status=result.status,
                    result_preview=result.preview,
                )
            )
            after_step = await self._after_step.run(
                AfterStepInput(
                    before_step=before_step,
                    result=result,
                    has_more=iteration < len(tool_calls) - 1,
                )
            )
            results.append(after_step.result)
        return results
