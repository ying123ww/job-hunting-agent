from __future__ import annotations

from interview_agent.cli import main


def test_cli_init_creates_workspace(monkeypatch, tmp_path, capsys) -> None:
    workspace = tmp_path / "cli-init"
    monkeypatch.delenv("INTERVIEW_AGENT_WORKSPACE_DIR", raising=False)

    main(["init", "--workspace", str(workspace)])

    output = capsys.readouterr().out
    assert "Created:" in output
    assert (workspace / "app.db").exists()
    assert (workspace / "memory" / "SELF.md").exists()


def test_cli_reset_recreates_workspace(monkeypatch, tmp_path, capsys) -> None:
    workspace = tmp_path / "cli-reset"
    monkeypatch.delenv("INTERVIEW_AGENT_WORKSPACE_DIR", raising=False)

    main(["init", "--workspace", str(workspace)])
    (workspace / "memory" / "HISTORY.md").write_text("hello", encoding="utf-8")

    main(["reset", "--workspace", str(workspace)])

    output = capsys.readouterr().out
    assert "workspace=" in output
    assert (workspace / "memory" / "HISTORY.md").read_text(encoding="utf-8") == ""
