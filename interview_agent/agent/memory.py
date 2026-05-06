from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from interview_agent.agent.events import ProactiveTickCompletedEvent, TurnCommittedEvent


DEFAULT_SELF_MD = """# Interview Copilot Agent Self Model

## Role
- 我是一个帮助用户准备面试的长期协作 agent。
- 我优先基于证据给建议，不在证据不足时编造判断。

## Boundaries
- 诊断结论应尽量回到 documents / chunks / questions / gaps。
- 当前用户显式表达优先于旧的 recent context。
"""

DEFAULT_NOW_MD = """# NOW

- current_focus:
- current_intent:
- current_jd_id:
- current_plan_id:
- current_goal:
- current_mock_session:
- latest_top_gap_dimensions:
- temporary_context:
- updated_at:
"""

DEFAULT_RECENT_CONTEXT_MD = """# RECENT_CONTEXT

- none
"""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _empty_items() -> list[str]:
    return []


@dataclass(slots=True)
class WorkingMemoryState:
    current_focus: str = ""
    current_intent: str = ""
    current_jd_id: str = ""
    current_plan_id: str = ""
    current_goal: str = ""
    current_mock_session: str = ""
    latest_top_gap_dimensions: list[str] = field(default_factory=_empty_items)
    temporary_context: list[str] = field(default_factory=_empty_items)
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WorkingMemoryState":
        return cls(
            current_focus=str(payload.get("current_focus", "") or ""),
            current_intent=str(payload.get("current_intent", "") or ""),
            current_jd_id=str(payload.get("current_jd_id", "") or ""),
            current_plan_id=str(payload.get("current_plan_id", "") or ""),
            current_goal=str(payload.get("current_goal", "") or ""),
            current_mock_session=str(payload.get("current_mock_session", "") or ""),
            latest_top_gap_dimensions=[str(item) for item in payload.get("latest_top_gap_dimensions", []) or [] if item],
            temporary_context=[str(item) for item in payload.get("temporary_context", []) or [] if item],
            updated_at=str(payload.get("updated_at", "") or ""),
        )

    def to_now_state(self) -> dict[str, str]:
        return {
            "current_focus": self.current_focus,
            "current_intent": self.current_intent,
            "current_jd_id": self.current_jd_id,
            "current_plan_id": self.current_plan_id,
            "current_goal": self.current_goal,
            "current_mock_session": self.current_mock_session,
            "latest_top_gap_dimensions": ",".join(self.latest_top_gap_dimensions),
            "temporary_context": " | ".join(self.temporary_context),
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class MemorySnapshot:
    long_term: str
    self_model: str
    recent_context: str
    pending: str
    now_text: str
    now_state: dict[str, str]
    working_memory: WorkingMemoryState
    history_excerpt: str


class AgentMemoryStore:
    """Markdown memory inspired by Akashic's profile-style memory layout."""

    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = memory_dir.resolve()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.self_file = self.memory_dir / "SELF.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.recent_context_file = self.memory_dir / "RECENT_CONTEXT.md"
        self.pending_file = self.memory_dir / "PENDING.md"
        self.now_file = self.memory_dir / "NOW.md"
        self.working_memory_file = self.memory_dir / "WORKING_MEMORY.json"
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._ensure_file(self.memory_file, "")
        self._ensure_file(self.self_file, DEFAULT_SELF_MD)
        self._ensure_file(self.history_file, "")
        self._ensure_file(self.recent_context_file, DEFAULT_RECENT_CONTEXT_MD)
        self._ensure_file(self.pending_file, "")
        self._ensure_file(self.now_file, DEFAULT_NOW_MD)
        self._ensure_file(
            self.working_memory_file,
            json.dumps(asdict(WorkingMemoryState()), ensure_ascii=False, indent=2) + "\n",
        )

    def _ensure_file(self, path: Path, default_content: str) -> None:
        if not path.exists():
            path.write_text(default_content, encoding="utf-8")

    def read_long_term(self) -> str:
        return self.memory_file.read_text(encoding="utf-8")

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def read_self(self) -> str:
        return self.self_file.read_text(encoding="utf-8")

    def write_self(self, content: str) -> None:
        self.self_file.write_text(content, encoding="utf-8")

    def read_history(self, *, max_chars: int = 0) -> str:
        text = self.history_file.read_text(encoding="utf-8")
        if max_chars > 0 and len(text) > max_chars:
            return text[-max_chars:]
        return text

    def append_history(self, entry: str) -> None:
        if not entry.strip():
            return
        with self.history_file.open("a", encoding="utf-8") as handle:
            handle.write(entry.rstrip() + "\n\n")

    def read_recent_context(self) -> str:
        return self.recent_context_file.read_text(encoding="utf-8")

    def write_recent_context(self, content: str) -> None:
        self.recent_context_file.write_text(content, encoding="utf-8")

    def rebuild_recent_context(self, *, max_entries: int = 8) -> None:
        history = self.read_history().strip()
        if not history:
            self.write_recent_context(DEFAULT_RECENT_CONTEXT_MD)
            return
        blocks = [block.strip() for block in history.split("\n\n") if block.strip()]
        tail = blocks[-max_entries:]
        content = "# RECENT_CONTEXT\n\n" + "\n\n".join(tail) + "\n"
        self.write_recent_context(content)

    def read_pending(self) -> str:
        return self.pending_file.read_text(encoding="utf-8")

    def append_pending(self, text: str) -> None:
        if not text.strip():
            return
        with self.pending_file.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")

    def clear_pending(self) -> None:
        self.pending_file.write_text("", encoding="utf-8")

    def read_now(self) -> str:
        return self.now_file.read_text(encoding="utf-8")

    def read_working_memory(self) -> WorkingMemoryState:
        try:
            payload = json.loads(self.working_memory_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if not any(payload.values()):
            payload = self._parse_now_text()
        return WorkingMemoryState.from_dict(payload)

    def write_working_memory(self, state: WorkingMemoryState) -> None:
        self.working_memory_file.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._write_now_from_working_memory(state)

    def read_now_state(self) -> dict[str, str]:
        return self.read_working_memory().to_now_state()

    def write_now_state(self, state: dict[str, str]) -> None:
        current = self.read_working_memory()
        current.current_focus = state.get("current_focus", current.current_focus)
        current.current_intent = state.get("current_intent", current.current_intent)
        current.current_jd_id = state.get("current_jd_id", current.current_jd_id)
        current.current_plan_id = state.get("current_plan_id", current.current_plan_id)
        current.current_goal = state.get("current_goal", current.current_goal)
        current.current_mock_session = state.get("current_mock_session", current.current_mock_session)
        if "latest_top_gap_dimensions" in state:
            current.latest_top_gap_dimensions = [
                item.strip() for item in state.get("latest_top_gap_dimensions", "").split(",") if item.strip()
            ]
        if "temporary_context" in state:
            current.temporary_context = [
                item.strip() for item in state.get("temporary_context", "").split("|") if item.strip()
            ]
        current.updated_at = state.get("updated_at", current.updated_at)
        self.write_working_memory(current)

    def _write_now_from_working_memory(self, state: WorkingMemoryState) -> None:
        lines = ["# NOW", ""]
        keys = [
            "current_focus",
            "current_intent",
            "current_jd_id",
            "current_plan_id",
            "current_goal",
            "current_mock_session",
            "latest_top_gap_dimensions",
            "temporary_context",
            "updated_at",
        ]
        now_state = state.to_now_state()
        for key in keys:
            lines.append(f"- {key}: {now_state.get(key, '')}")
        self.now_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _parse_now_text(self) -> dict[str, object]:
        state: dict[str, object] = {}
        for line in self.read_now().splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ") or ":" not in stripped:
                continue
            key, value = stripped[2:].split(":", 1)
            state[key.strip()] = value.strip()
        if "latest_top_gap_dimensions" in state:
            state["latest_top_gap_dimensions"] = [
                item.strip() for item in str(state["latest_top_gap_dimensions"]).split(",") if item.strip()
            ]
        if "temporary_context" in state:
            state["temporary_context"] = [
                item.strip() for item in str(state["temporary_context"]).split("|") if item.strip()
            ]
        return state

    def snapshot(self, *, max_history_chars: int = 3000) -> MemorySnapshot:
        working_memory = self.read_working_memory()
        return MemorySnapshot(
            long_term=self.read_long_term(),
            self_model=self.read_self(),
            recent_context=self.read_recent_context(),
            pending=self.read_pending(),
            now_text=self.read_now(),
            now_state=working_memory.to_now_state(),
            working_memory=working_memory,
            history_excerpt=self.read_history(max_chars=max_history_chars),
        )


class MemoryLifecycleHandler:
    def __init__(self, memory_store: AgentMemoryStore) -> None:
        self.memory_store = memory_store

    async def handle_turn_committed(self, event: TurnCommittedEvent) -> None:
        timestamp = event.timestamp.isoformat(timespec="minutes")
        entry = (
            f"[{timestamp}] USER ({event.intent})\n{event.message}\n\n"
            f"[{timestamp}] ASSISTANT\n{event.reply}"
        )
        self.memory_store.append_history(entry)
        if event.pending_memory:
            self.memory_store.append_pending(event.pending_memory)
        current = self.memory_store.read_working_memory()
        current.current_focus = event.message[:120]
        current.current_intent = event.intent
        current.current_jd_id = event.current_jd_id or ""
        current.current_plan_id = event.generated_plan_id or ""
        current.current_goal = self._derive_goal(
            current_intent=event.intent,
            top_gap_dimensions=event.top_gap_dimensions,
            fallback=event.message[:120],
        )
        current.latest_top_gap_dimensions = list(event.top_gap_dimensions)
        current.temporary_context = self._trim_context(
            [*current.temporary_context, event.message[:120], event.reply[:160]]
        )
        current.updated_at = timestamp
        self.memory_store.write_working_memory(current)
        self.memory_store.rebuild_recent_context()

    async def handle_proactive_tick_completed(self, event: ProactiveTickCompletedEvent) -> None:
        if event.action == "skip":
            return
        timestamp = event.timestamp.isoformat(timespec="minutes")
        entry = f"[{timestamp}] AGENT (proactive/{event.action})\n{event.message}"
        self.memory_store.append_history(entry)
        current = self.memory_store.read_working_memory()
        current.current_focus = event.message[:120]
        current.current_intent = f"proactive:{event.action}"
        current.current_jd_id = event.current_jd_id or current.current_jd_id
        current.current_plan_id = event.generated_plan_id or current.current_plan_id
        current.current_goal = event.message[:120]
        current.temporary_context = self._trim_context([*current.temporary_context, event.message[:160]])
        current.updated_at = timestamp
        self.memory_store.write_working_memory(current)
        self.memory_store.rebuild_recent_context()

    def _derive_goal(self, *, current_intent: str, top_gap_dimensions: list[str], fallback: str) -> str:
        if top_gap_dimensions:
            return f"优先修复 {top_gap_dimensions[0]}"
        if current_intent == "plan":
            return "执行当前计划中的最高优先级任务"
        if current_intent == "diagnosis":
            return "明确当前最高优先级短板"
        return fallback

    def _trim_context(self, items: list[str], *, limit: int = 4) -> list[str]:
        normalized = [item.strip() for item in items if item.strip()]
        return normalized[-limit:]
