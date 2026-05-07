from __future__ import annotations

from interview_agent.app.config import AppSettings
from interview_agent.app.workspace_init import init_workspace


def test_init_workspace_creates_missing_assets_without_overwriting_existing_files(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-init-a"
    monkeypatch.setenv("INTERVIEW_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", "")
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", "")

    settings = AppSettings(_env_file=None)
    summary = init_workspace(settings=settings, force=False)

    assert (workspace / "app.db").exists()
    assert (workspace / "chroma").exists()
    assert (workspace / "memory" / "SELF.md").exists()
    assert summary.created

    history_path = workspace / "memory" / "HISTORY.md"
    history_path.write_text("existing history", encoding="utf-8")

    summary = init_workspace(settings=settings, force=False)

    assert history_path.read_text(encoding="utf-8") == "existing history"
    assert history_path in summary.skipped


def test_init_workspace_force_rewrites_templates_but_preserves_database(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-init-b"
    monkeypatch.setenv("INTERVIEW_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", "")
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", "")

    settings = AppSettings(_env_file=None)
    _ = init_workspace(settings=settings, force=False)

    history_path = workspace / "memory" / "HISTORY.md"
    history_path.write_text("custom history", encoding="utf-8")
    db_path = workspace / "app.db"
    db_mtime_before = db_path.stat().st_mtime

    summary = init_workspace(settings=settings, force=True)

    assert history_path.read_text(encoding="utf-8") == ""
    assert history_path in summary.overwritten
    assert db_path.exists()
    assert db_path.stat().st_mtime == db_mtime_before
    assert db_path in summary.skipped
