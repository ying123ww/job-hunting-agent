from __future__ import annotations

from interview_agent.app.config import AppSettings, get_settings
from interview_agent.core.container import AppContainer


def test_workspace_defaults_mount_runtime_state_under_workspace(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-a"
    monkeypatch.setenv("INTERVIEW_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", "")
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", "")

    settings = AppSettings(_env_file=None)

    assert settings.workspace_path == workspace.resolve()
    assert settings.sqlite_path == (workspace / "app.db").resolve()
    assert settings.chroma_path == (workspace / "chroma").resolve()
    assert settings.memory_path == (workspace / "memory").resolve()


def test_explicit_runtime_paths_override_workspace_defaults(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-b"
    db_path = tmp_path / "custom" / "app.db"
    chroma_path = tmp_path / "custom" / "chroma"
    memory_path = tmp_path / "custom" / "memory"
    monkeypatch.setenv("INTERVIEW_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(chroma_path))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(memory_path))

    settings = AppSettings(_env_file=None)

    assert settings.sqlite_path == db_path.resolve()
    assert settings.chroma_path == chroma_path.resolve()
    assert settings.memory_path == memory_path.resolve()


def test_container_build_creates_runtime_state_inside_workspace(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-c"
    monkeypatch.setenv("INTERVIEW_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", "")
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", "")
    get_settings.cache_clear()

    settings = get_settings()
    _ = AppContainer.build(settings)

    assert (workspace / "app.db").exists()
    assert (workspace / "chroma").exists()
    assert (workspace / "memory" / "SELF.md").exists()
