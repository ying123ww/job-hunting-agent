from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from interview_agent.agent.memory import (
    AgentMemoryStore,
    DEFAULT_NOW_MD,
    DEFAULT_RECENT_CONTEXT_MD,
    DEFAULT_SELF_MD,
    WorkingMemoryState,
)
from interview_agent.app.config import AppSettings
from interview_agent.storage.database import DatabaseManager


_TEXT_FILES: dict[str, str] = {
    "memory/MEMORY.md": "",
    "memory/SELF.md": DEFAULT_SELF_MD,
    "memory/HISTORY.md": "",
    "memory/RECENT_CONTEXT.md": DEFAULT_RECENT_CONTEXT_MD,
    "memory/PENDING.md": "",
    "memory/NOW.md": DEFAULT_NOW_MD,
}

_JSON_FILES: dict[str, object] = {
    "memory/WORKING_MEMORY.json": asdict(WorkingMemoryState()),
}


@dataclass(slots=True)
class InitSummary:
    created: list[Path] = field(default_factory=list)
    overwritten: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def _write_text_file(path: Path, content: str, *, force: bool, summary: InitSummary) -> None:
    existed = path.exists()
    if existed and not force:
        summary.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if existed:
        summary.overwritten.append(path)
    else:
        summary.created.append(path)


def _write_json_file(path: Path, payload: object, *, force: bool, summary: InitSummary) -> None:
    existed = path.exists()
    if existed and not force:
        summary.skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if existed:
        summary.overwritten.append(path)
    else:
        summary.created.append(path)


def _ensure_directory(path: Path, *, summary: InitSummary) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if existed:
        summary.skipped.append(path)
    else:
        summary.created.append(path)


def init_workspace(*, settings: AppSettings, force: bool = False) -> InitSummary:
    summary = InitSummary()
    workspace = settings.workspace_path

    _ensure_directory(workspace, summary=summary)
    _ensure_directory(settings.memory_path, summary=summary)
    _ensure_directory(settings.chroma_path, summary=summary)

    for rel_path, content in _TEXT_FILES.items():
        _write_text_file(workspace / rel_path, content, force=force, summary=summary)
    for rel_path, payload in _JSON_FILES.items():
        _write_json_file(workspace / rel_path, payload, force=force, summary=summary)

    sqlite_path = settings.sqlite_path
    db_existed = sqlite_path.exists() if sqlite_path is not None else False
    AgentMemoryStore(settings.memory_path)
    DatabaseManager(settings.resolved_database_url).create_all()

    if sqlite_path is not None:
        if db_existed:
            summary.skipped.append(sqlite_path)
        else:
            summary.created.append(sqlite_path)

    summary.notes.append(f"workspace initialized at: {workspace}")
    if force:
        summary.notes.append(
            "--force only resets workspace template files; app.db and chroma data are preserved."
        )
    else:
        summary.notes.append("existing runtime data was preserved; missing files were created in place.")
    summary.next_steps.extend(
        [
            f"Set INTERVIEW_AGENT_WORKSPACE_DIR={workspace}",
            "Start the API or bot process against this workspace.",
        ]
    )
    return summary
