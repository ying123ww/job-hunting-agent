from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import (
    ProactiveDriftCompletedEvent,
    ProactiveDriftStartedEvent,
    ProactiveTickCompletedEvent,
    ProactiveTickStartedEvent,
)
from interview_agent.agent.lifecycle import Phase, PhaseFrame
from interview_agent.agent.memory import AgentMemoryStore, MemorySnapshot
from interview_agent.agent.plugins import PluginManager
from interview_agent.diagnosis.service import GapAnalysisService
from interview_agent.planning.service import PlanService


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _empty_lifecycle() -> list[str]:
    return []


@dataclass(slots=True)
class ProactiveTickContext:
    session: Session
    tick_id: str
    user_id: str
    current_jd_id: str | None
    force: bool
    memory_snapshot: MemorySnapshot
    current_plan_id: str | None = None
    latest_gaps: list[object] = field(default_factory=list)
    today_tasks: list[object] = field(default_factory=list)
    recent_context: str = ""
    semantic_memory_block: str = ""
    drift_entered: bool = False
    lifecycle: list[str] = field(default_factory=_empty_lifecycle)


@dataclass(slots=True)
class ProactiveTickResult:
    tick_id: str
    action: str
    message: str
    current_jd_id: str | None = None
    generated_plan_id: str | None = None
    drift_entered: bool = False
    lifecycle: list[str] = field(default_factory=_empty_lifecycle)


@dataclass(slots=True)
class BeforeTickInput:
    session: Session
    user_id: str
    current_jd_id: str | None
    force: bool


@dataclass(slots=True)
class BeforeTickFrame(PhaseFrame[BeforeTickInput, ProactiveTickContext]):
    pass


@dataclass(slots=True)
class DriftInput:
    before_tick: ProactiveTickContext


@dataclass(slots=True)
class DriftContext:
    before_tick: ProactiveTickContext
    message: str
    lifecycle: list[str] = field(default_factory=_empty_lifecycle)


@dataclass(slots=True)
class DriftFrame(PhaseFrame[DriftInput, DriftContext]):
    pass


@dataclass(slots=True)
class AfterTickInput:
    before_tick: ProactiveTickContext
    result: ProactiveTickResult


@dataclass(slots=True)
class AfterTickFrame(PhaseFrame[AfterTickInput, ProactiveTickResult]):
    pass


class _AssignTickIdModule:
    async def run(self, frame: BeforeTickFrame) -> BeforeTickFrame:
        frame.slots["tick_id"] = f"tick_{utcnow().strftime('%H%M%S')}"
        frame.slots["lifecycle"] = ["ProactiveBeforeTick"]
        return frame


class _LoadSnapshotModule:
    def __init__(self, memory_store: AgentMemoryStore) -> None:
        self.memory_store = memory_store

    async def run(self, frame: BeforeTickFrame) -> BeforeTickFrame:
        snapshot = self.memory_store.snapshot()
        frame.slots["memory_snapshot"] = snapshot
        frame.slots["recent_context"] = snapshot.recent_context
        return frame


class _CollectSignalsModule:
    def __init__(self, diagnosis: GapAnalysisService, planning: PlanService) -> None:
        self.diagnosis = diagnosis
        self.planning = planning

    async def run(self, frame: BeforeTickFrame) -> BeforeTickFrame:
        overall_risk, gaps = self.diagnosis.current(frame.input.session, user_id=frame.input.user_id, limit=3)
        plan = self.planning.today(frame.input.session, user_id=frame.input.user_id, day=date.today())
        frame.slots["overall_risk"] = overall_risk
        frame.slots["latest_gaps"] = gaps
        frame.slots["plan"] = plan
        frame.slots["today_tasks"] = list(plan.tasks) if plan is not None else []
        return frame


class _EmitStartedModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: BeforeTickFrame) -> BeforeTickFrame:
        event = await self.event_bus.emit(
            ProactiveTickStartedEvent(
                tick_id=frame.slots["tick_id"],
                user_id=frame.input.user_id,
                current_jd_id=frame.input.current_jd_id,
            )
        )
        frame.slots["current_jd_id"] = event.current_jd_id
        return frame


class _ReturnBeforeTickModule:
    async def run(self, frame: BeforeTickFrame) -> BeforeTickFrame:
        frame.output = ProactiveTickContext(
            session=frame.input.session,
            tick_id=frame.slots["tick_id"],
            user_id=frame.input.user_id,
            current_jd_id=frame.slots.get("current_jd_id", frame.input.current_jd_id),
            force=frame.input.force,
            memory_snapshot=frame.slots["memory_snapshot"],
            current_plan_id=getattr(frame.slots.get("plan"), "plan_id", None),
            latest_gaps=list(frame.slots["latest_gaps"]),
            today_tasks=list(frame.slots["today_tasks"]),
            recent_context=str(frame.slots["recent_context"]),
            semantic_memory_block=str(frame.slots.get("memory2:block", "")),
            lifecycle=list(frame.slots["lifecycle"]),
        )
        return frame


class _EmitDriftStartedModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: DriftFrame) -> DriftFrame:
        before_tick = frame.input.before_tick
        await self.event_bus.fanout(
            ProactiveDriftStartedEvent(
                tick_id=before_tick.tick_id,
                user_id=before_tick.user_id,
                current_jd_id=before_tick.current_jd_id,
                recent_context=before_tick.recent_context,
                semantic_memory_block=before_tick.semantic_memory_block,
            )
        )
        return frame


class DriftRunner:
    def run(self, ctx: ProactiveTickContext) -> str:
        if ctx.latest_gaps:
            top_gap = getattr(ctx.latest_gaps[0], "dimension", "general")
            return f"今天没有特别紧急的提醒，但你可以顺手做一个 drift 动作：用 10 分钟整理 `{top_gap}` 的标准回答框架。"
        if ctx.semantic_memory_block.strip():
            return "今天没有新的高优先级告警。你可以先回看一下最近的语义记忆，把其中最相关的一条整理成一版面试话术。"
        if ctx.recent_context.strip():
            return "今天没有新的高优先级告警。可以回看一下最近上下文里提到的任务，顺手推进一个最小动作。"
        return "今天没有新的高优先级提醒。你可以先补一题历史错题，保持面试手感。"


class _RunDriftModule:
    def __init__(self, drift_runner: DriftRunner) -> None:
        self.drift_runner = drift_runner

    async def run(self, frame: DriftFrame) -> DriftFrame:
        frame.slots["message"] = self.drift_runner.run(frame.input.before_tick)
        lifecycle = list(frame.input.before_tick.lifecycle)
        lifecycle.append("ProactiveDrift")
        frame.slots["lifecycle"] = lifecycle
        return frame


class _EmitDriftCompletedModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: DriftFrame) -> DriftFrame:
        before_tick = frame.input.before_tick
        await self.event_bus.fanout(
            ProactiveDriftCompletedEvent(
                tick_id=before_tick.tick_id,
                user_id=before_tick.user_id,
                current_jd_id=before_tick.current_jd_id,
                message=str(frame.slots["message"]),
            )
        )
        return frame


class _ReturnDriftModule:
    async def run(self, frame: DriftFrame) -> DriftFrame:
        frame.output = DriftContext(
            before_tick=frame.input.before_tick,
            message=str(frame.slots["message"]),
            lifecycle=list(frame.slots["lifecycle"]),
        )
        return frame


class _CommitCompletedModule:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def run(self, frame: AfterTickFrame) -> AfterTickFrame:
        result = frame.input.result
        await self.event_bus.fanout(
            ProactiveTickCompletedEvent(
                tick_id=result.tick_id,
                user_id=frame.input.before_tick.user_id,
                action=result.action,
                message=result.message,
                current_jd_id=result.current_jd_id,
                generated_plan_id=result.generated_plan_id,
                drift_entered=result.drift_entered,
            )
        )
        return frame


class _ReturnAfterTickModule:
    async def run(self, frame: AfterTickFrame) -> AfterTickFrame:
        frame.output = frame.input.result
        return frame


class ProactiveTickService:
    def __init__(
        self,
        *,
        diagnosis: GapAnalysisService,
        planning: PlanService,
        memory_store: AgentMemoryStore,
        drift_runner: DriftRunner,
        event_bus: EventBus,
        plugin_manager: PluginManager,
    ) -> None:
        self.diagnosis = diagnosis
        self.planning = planning
        self.memory_store = memory_store
        self.drift_runner = drift_runner
        self.event_bus = event_bus
        self.plugin_manager = plugin_manager
        self._before_tick = Phase(
            [
                *self.plugin_manager.phase_modules("proactive_before_tick_modules_early"),
                _AssignTickIdModule(),
                _LoadSnapshotModule(memory_store),
                _CollectSignalsModule(diagnosis, planning),
                _EmitStartedModule(event_bus),
                *self.plugin_manager.phase_modules("proactive_before_tick_modules_late"),
                _ReturnBeforeTickModule(),
            ],
            frame_factory=BeforeTickFrame,
        )
        self._drift = Phase(
            [
                *self.plugin_manager.phase_modules("proactive_drift_modules_early"),
                _EmitDriftStartedModule(event_bus),
                _RunDriftModule(drift_runner),
                _EmitDriftCompletedModule(event_bus),
                *self.plugin_manager.phase_modules("proactive_drift_modules_late"),
                _ReturnDriftModule(),
            ],
            frame_factory=DriftFrame,
        )
        self._after_tick = Phase(
            [
                *self.plugin_manager.phase_modules("proactive_after_tick_modules_early"),
                _CommitCompletedModule(event_bus),
                *self.plugin_manager.phase_modules("proactive_after_tick_modules_late"),
                _ReturnAfterTickModule(),
            ],
            frame_factory=AfterTickFrame,
        )

    def tick(self, session: Session, *, user_id: str, current_jd_id: str | None, force: bool = False) -> ProactiveTickResult:
        before_tick = self._run_async(
            self._before_tick.run(
                BeforeTickInput(
                    session=session,
                    user_id=user_id,
                    current_jd_id=current_jd_id,
                    force=force,
                )
            )
        )
        result = self._decide(before_tick)
        return self._run_async(self._after_tick.run(AfterTickInput(before_tick=before_tick, result=result)))

    def _decide(self, before_tick: ProactiveTickContext) -> ProactiveTickResult:
        if not before_tick.force and not before_tick.latest_gaps and not before_tick.today_tasks:
            return ProactiveTickResult(
                tick_id=before_tick.tick_id,
                action="skip",
                message="当前还没有足够的数据触发 proactive tick。",
                current_jd_id=before_tick.current_jd_id,
                lifecycle=[*before_tick.lifecycle, "ProactiveAfterTick"],
            )

        if before_tick.today_tasks:
            top_task = before_tick.today_tasks[0]
            return ProactiveTickResult(
                tick_id=before_tick.tick_id,
                action="reply",
                message=(
                    f"提醒一下，你今天最值得先推进的是：{top_task.title}。"
                    f"预计 {top_task.duration_min} 分钟，理由是：{top_task.reason}"
                ),
                current_jd_id=before_tick.current_jd_id,
                generated_plan_id=before_tick.current_plan_id,
                lifecycle=[*before_tick.lifecycle, "ProactiveAfterTick"],
            )

        if before_tick.latest_gaps:
            generated = self.planning.generate(
                before_tick.session,
                user_id=before_tick.user_id,
                jd_id=before_tick.current_jd_id,
                gap_limit=3,
                day=date.today(),
            )
            top_gap = before_tick.latest_gaps[0]
            return ProactiveTickResult(
                tick_id=before_tick.tick_id,
                action="reply",
                message=(
                    f"我刚帮你看了一眼当前风险，最需要先修的是 `{top_gap.dimension}`。"
                    f"我已经生成了今天的计划，先从第一条任务开始。"
                ),
                current_jd_id=before_tick.current_jd_id,
                generated_plan_id=generated.plan_id,
                lifecycle=[*before_tick.lifecycle, "ProactiveAfterTick"],
            )

        drift = self._run_async(self._drift.run(DriftInput(before_tick=before_tick)))
        return ProactiveTickResult(
            tick_id=before_tick.tick_id,
            action="drift",
            message=drift.message,
            current_jd_id=before_tick.current_jd_id,
            drift_entered=True,
            lifecycle=[*drift.lifecycle, "ProactiveAfterTick"],
        )

    def _run_async(self, awaitable):
        import asyncio

        return asyncio.run(awaitable)
