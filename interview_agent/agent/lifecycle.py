from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import (
    AfterReasoningEvent,
    AfterStepEvent,
    BeforeReasoningEvent,
    BeforeStepEvent,
    BeforeTurnEvent,
    ProactiveDriftCompletedEvent,
    ProactiveDriftStartedEvent,
    ProactiveTickCompletedEvent,
    ProactiveTickStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    TurnCommittedEvent,
)


logger = logging.getLogger(__name__)

I = TypeVar("I")
O = TypeVar("O")
F = TypeVar("F", bound="PhaseFrame[Any, Any]")


def _empty_slots() -> dict[str, Any]:
    return {}


def collect_prefixed_slots(
    slots: Mapping[str, object],
    prefix: str,
    *,
    reserved: Collection[str] = (),
) -> dict[str, object]:
    values: dict[str, object] = {}
    reserved_fields = set(reserved)
    for key, value in slots.items():
        if not key.startswith(prefix):
            continue
        field_name = key.removeprefix(prefix)
        if not field_name or field_name in reserved_fields:
            continue
        values[field_name] = value
    return values


@dataclass
class PhaseFrame(Generic[I, O]):
    input: I
    slots: dict[str, Any] = field(default_factory=_empty_slots)
    output: O | None = None


class PhaseModule(Protocol[F]):
    async def run(self, frame: F) -> F:
        ...


class Phase(Generic[I, O, F]):
    def __init__(
        self,
        modules: Sequence[PhaseModule[F]],
        *,
        frame_factory: Callable[[I], F],
    ) -> None:
        self._modules = list(modules)
        self._frame_factory = frame_factory
        self._validate()

    async def run(self, input: I) -> O:
        frame = self._frame_factory(input)
        for module in self._modules:
            frame = await module.run(frame)
        if frame.output is None:
            raise RuntimeError("Phase 模块链未产生 output")
        return frame.output

    def _validate(self) -> None:
        provided: set[str] = set()
        for index, module in enumerate(self._modules):
            requires = tuple(getattr(module, "requires", ()))
            produces = tuple(getattr(module, "produces", ()))
            for slot in requires:
                if slot not in provided:
                    logger.warning(
                        "Phase slot 未闭合: module=%d name=%s requires=%s",
                        index,
                        module.__class__.__name__,
                        slot,
                    )
            provided.update(str(slot) for slot in produces)


class TurnLifecycle:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def on_before_turn(self, handler) -> None:
        self._event_bus.on(BeforeTurnEvent, handler)

    def on_before_reasoning(self, handler) -> None:
        self._event_bus.on(BeforeReasoningEvent, handler)

    def on_before_step(self, handler) -> None:
        self._event_bus.on(BeforeStepEvent, handler)

    def on_after_step(self, handler) -> None:
        self._event_bus.on(AfterStepEvent, handler)

    def on_after_reasoning(self, handler) -> None:
        self._event_bus.on(AfterReasoningEvent, handler)

    def on_after_turn(self, handler) -> None:
        self._event_bus.on(TurnCommittedEvent, handler)

    def on_tool_call_started(self, handler) -> None:
        self._event_bus.on(ToolCallStartedEvent, handler)

    def on_tool_call_completed(self, handler) -> None:
        self._event_bus.on(ToolCallCompletedEvent, handler)

    def on_proactive_tick_started(self, handler) -> None:
        self._event_bus.on(ProactiveTickStartedEvent, handler)

    def on_proactive_drift_started(self, handler) -> None:
        self._event_bus.on(ProactiveDriftStartedEvent, handler)

    def on_proactive_drift_completed(self, handler) -> None:
        self._event_bus.on(ProactiveDriftCompletedEvent, handler)

    def on_proactive_tick_completed(self, handler) -> None:
        self._event_bus.on(ProactiveTickCompletedEvent, handler)
