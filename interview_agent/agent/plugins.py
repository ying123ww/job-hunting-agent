from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from interview_agent.agent.lifecycle import PhaseModule, TurnLifecycle


class AgentRuntimePlugin(Protocol):
    def bind(self, lifecycle: TurnLifecycle) -> None:
        ...

    def before_turn_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def before_turn_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def before_reasoning_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def before_reasoning_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def after_reasoning_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def after_reasoning_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def before_step_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def before_step_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def after_step_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def after_step_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def after_turn_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def after_turn_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def proactive_before_tick_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def proactive_before_tick_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def proactive_drift_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def proactive_drift_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def proactive_after_tick_modules_early(self) -> Sequence[PhaseModule[Any]]:
        return ()

    def proactive_after_tick_modules_late(self) -> Sequence[PhaseModule[Any]]:
        return ()


@dataclass(slots=True)
class PluginManager:
    plugins: list[AgentRuntimePlugin]

    def bind(self, lifecycle: TurnLifecycle) -> None:
        for plugin in self.plugins:
            plugin.bind(lifecycle)

    def phase_modules(self, attr_name: str) -> list[PhaseModule[Any]]:
        modules: list[PhaseModule[Any]] = []
        for plugin in self.plugins:
            provider = getattr(plugin, attr_name, None)
            if provider is None:
                continue
            modules.extend(list(provider()))
        return modules
