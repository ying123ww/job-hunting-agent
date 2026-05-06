from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from interview_agent.agent.lifecycle import TurnLifecycle
from interview_agent.agent.plugins import AgentRuntimePlugin
from interview_agent.memory2.injection_planner import build_memory_injection_block
from interview_agent.memory2.memorizer import SemanticMemorizer
from interview_agent.memory2.retriever import SemanticMemoryRetriever


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class _SemanticMemoryRecallModule:
    retriever: SemanticMemoryRetriever

    async def run(self, frame):
        before_turn = frame.input.before_turn
        hits = self.retriever.retrieve(
            before_turn.session,
            user_id=before_turn.user_id,
            query=before_turn.message,
            limit=5,
        )
        frame.slots["memory2:hits"] = hits
        frame.slots["memory2:block"] = build_memory_injection_block(hits)
        return frame


@dataclass(slots=True)
class _ProactiveSemanticRecallModule:
    retriever: SemanticMemoryRetriever

    async def run(self, frame):
        snapshot = frame.slots["memory_snapshot"]
        query = (
            frame.slots.get("current_jd_id")
            or frame.input.current_jd_id
            or snapshot.now_state.get("current_focus")
            or snapshot.recent_context
            or "today interview prep"
        )
        hits = self.retriever.retrieve(
            frame.input.session,
            user_id=frame.input.user_id,
            query=str(query),
            limit=4,
        )
        frame.slots["memory2:proactive_hits"] = hits
        frame.slots["memory2:block"] = build_memory_injection_block(hits)
        return frame


@dataclass(slots=True)
class _SemanticMemoryPersistModule:
    memorizer: SemanticMemorizer

    async def run(self, frame):
        after_reasoning = frame.input.after_reasoning
        session = after_reasoning.session
        source_ref = after_reasoning.turn_id
        pending_memory = after_reasoning.decision.pending_memory or ""
        if pending_memory.strip():
            writes = self.memorizer.memorize_pending(
                session,
                user_id=after_reasoning.user_id,
                pending_text=pending_memory,
                source_ref=source_ref,
            )
            frame.slots["memory2:writes"] = writes
        summary = (
            f"intent={after_reasoning.decision.intent}; "
            f"message={after_reasoning.message[:120]}; "
            f"reply={after_reasoning.decision.reply[:180]}"
        )
        self.memorizer.memorize_turn_summary(
            session,
            user_id=after_reasoning.user_id,
            summary=summary,
            source_ref=source_ref,
            extra_json={
                "intent": after_reasoning.decision.intent,
                "current_jd_id": after_reasoning.current_jd_id or "",
                "ts": utcnow().isoformat(timespec="seconds"),
            },
        )
        return frame


@dataclass(slots=True)
class _ProactiveSemanticPersistModule:
    memorizer: SemanticMemorizer

    async def run(self, frame):
        before_tick = frame.input.before_tick
        result = frame.input.result
        self.memorizer.memorize_turn_summary(
            before_tick.session,
            user_id=before_tick.user_id,
            summary=(
                f"proactive action={result.action}; "
                f"message={result.message[:180]}"
            ),
            source_ref=result.tick_id,
            extra_json={
                "action": result.action,
                "current_jd_id": result.current_jd_id or "",
                "kind": "proactive_tick",
            },
        )
        return frame


class SemanticMemoryPlugin(AgentRuntimePlugin):
    def __init__(
        self,
        *,
        retriever: SemanticMemoryRetriever,
        memorizer: SemanticMemorizer,
    ) -> None:
        self.retriever = retriever
        self.memorizer = memorizer

    def bind(self, lifecycle: TurnLifecycle) -> None:
        return None

    def before_reasoning_modules_early(self):
        return (_SemanticMemoryRecallModule(self.retriever),)

    def after_turn_modules_early(self):
        return (_SemanticMemoryPersistModule(self.memorizer),)

    def proactive_before_tick_modules_late(self):
        return (_ProactiveSemanticRecallModule(self.retriever),)

    def proactive_after_tick_modules_early(self):
        return (_ProactiveSemanticPersistModule(self.memorizer),)
