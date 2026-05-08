from __future__ import annotations

import asyncio
from types import SimpleNamespace

from interview_agent.app.config import get_settings
from interview_agent.app.main import compile_resume, create_app, resume_pdf, save_resume_source
from interview_agent.app.schemas import ResumeSourceUpdateRequest
from interview_agent.core.container import AppContainer


def _make_request(monkeypatch, tmp_path) -> SimpleNamespace:
    monkeypatch.setenv("INTERVIEW_AGENT_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    app = create_app()
    app.state.container = AppContainer.build(settings)
    return SimpleNamespace(app=app)


def _run(awaitable):
    return asyncio.run(awaitable)


def test_compile_success_updates_state_and_exposes_pdf(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    service = request.app.state.container.resume_workspace
    settings = request.app.state.container.settings
    _run(
        save_resume_source(
            request,
            ResumeSourceUpdateRequest(
                source="\\documentclass{article}\\begin{document}ok\\end{document}"
            ),
        )
    )

    def fake_run(*args, **kwargs):
        settings.resume_pdf_path.write_bytes(b"%PDF-1.4 test")
        (settings.resume_path / "resume.log").write_text(
            "Output written on resume.pdf",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="compiled", stderr="")

    monkeypatch.setattr(service, "_resolve_compiler_path", lambda: "/tmp/tectonic")
    monkeypatch.setattr("interview_agent.resume.service.subprocess.run", fake_run)

    response = _run(compile_resume(request))

    assert response.last_compile_status == "success"
    assert response.pdf_exists is True
    file_response = _run(resume_pdf(request))
    assert str(file_response.path).endswith("resume.pdf")


def test_compile_uses_default_tectonic_command(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    service = request.app.state.container.resume_workspace
    settings = request.app.state.container.settings
    captured: dict[str, object] = {}
    _run(
        save_resume_source(
            request,
            ResumeSourceUpdateRequest(
                source="\\documentclass{article}\\begin{document}ok\\end{document}"
            ),
        )
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        settings.resume_pdf_path.write_bytes(b"%PDF-1.4 test")
        (settings.resume_path / "resume.log").write_text(
            "Output written on resume.pdf",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="compiled", stderr="")

    monkeypatch.setattr(service, "_resolve_compiler_path", lambda: "/tmp/tectonic")
    monkeypatch.setattr("interview_agent.resume.service.subprocess.run", fake_run)

    _run(compile_resume(request))

    assert captured["command"] == [
        "/tmp/tectonic",
        "-X",
        "compile",
        "resume.tex",
        "--outdir",
        str(settings.resume_path),
        "--keep-logs",
    ]


def test_compile_failure_preserves_previous_pdf(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    service = request.app.state.container.resume_workspace
    settings = request.app.state.container.settings
    _run(
        save_resume_source(
            request,
            ResumeSourceUpdateRequest(
                source="\\documentclass{article}\\begin{document}ok\\end{document}"
            ),
        )
    )
    settings.resume_pdf_path.write_bytes(b"%PDF-old")

    def fake_run(*args, **kwargs):
        settings.resume_pdf_path.write_bytes(b"%PDF-broken")
        (settings.resume_path / "resume.log").write_text(
            "! Undefined control sequence.",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=1, stdout="", stderr="error")

    monkeypatch.setattr(service, "_resolve_compiler_path", lambda: "/tmp/tectonic")
    monkeypatch.setattr("interview_agent.resume.service.subprocess.run", fake_run)

    response = _run(compile_resume(request))

    assert response.last_compile_status == "failed"
    assert response.pdf_exists is True
    assert settings.resume_pdf_path.read_bytes() == b"%PDF-old"
    assert "Undefined control sequence" in (response.last_compile_error_summary or "")
