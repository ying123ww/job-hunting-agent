from __future__ import annotations

from dataclasses import dataclass
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
- latest_top_gap_dimensions:
- updated_at:
"""

DEFAULT_RECENT_CONTEXT_MD = """# RECENT_CONTEXT

- none
"""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class MemorySnapshot:
    long_term: str
    self_model: str
    recent_context: str
    pending: str
    now_text: str
    now_state: dict[str, str]
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
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._ensure_file(self.memory_file, "")
        self._ensure_file(self.self_file, DEFAULT_SELF_MD)
        self._ensure_file(self.history_file, "")
        self._ensure_file(self.recent_context_file, DEFAULT_RECENT_CONTEXT_MD)
        self._ensure_file(self.pending_file, "")
        self._ensure_file(self.now_file, DEFAULT_NOW_MD)

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

    def read_now_state(self) -> dict[str, str]:
        state: dict[str, str] = {}
        for line in self.read_now().splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ") or ":" not in stripped:
                continue
            key, value = stripped[2:].split(":", 1)
            state[key.strip()] = value.strip()
        return state

    def write_now_state(self, state: dict[str, str]) -> None:
        lines = ["# NOW", ""]
        keys = [
            "current_focus",
            "current_intent",
            "current_jd_id",
            "current_plan_id",
            "latest_top_gap_dimensions",
            "updated_at",
        ]
        for key in keys:
            lines.append(f"- {key}: {state.get(key, '')}")
        self.now_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def snapshot(self, *, max_history_chars: int = 3000) -> MemorySnapshot:
        return MemorySnapshot(
            long_term=self.read_long_term(),
            self_model=self.read_self(),
            recent_context=self.read_recent_context(),
            pending=self.read_pending(),
            now_text=self.read_now(),
            now_state=self.read_now_state(),
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
        self.memory_store.write_now_state(
            {
                "current_focus": event.message[:120],
                "current_intent": event.intent,
                "current_jd_id": event.current_jd_id or "",
                "current_plan_id": event.generated_plan_id or "",
                "latest_top_gap_dimensions": ",".join(event.top_gap_dimensions),
                "updated_at": timestamp,
            }
        )
        self.memory_store.rebuild_recent_context()

    async def handle_proactive_tick_completed(self, event: ProactiveTickCompletedEvent) -> None:
        if event.action == "skip":
            return
        timestamp = event.timestamp.isoformat(timespec="minutes")
        entry = f"[{timestamp}] AGENT (proactive/{event.action})\n{event.message}"
        self.memory_store.append_history(entry)
        current = self.memory_store.read_now_state()
        current.update(
            {
                "current_focus": event.message[:120],
                "current_intent": f"proactive:{event.action}",
                "current_jd_id": event.current_jd_id or current.get("current_jd_id", ""),
                "current_plan_id": event.generated_plan_id or current.get("current_plan_id", ""),
                "updated_at": timestamp,
            }
        )
        self.memory_store.write_now_state(current)
        self.memory_store.rebuild_recent_context()
