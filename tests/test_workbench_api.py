from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from interview_agent.app.config import get_settings
from interview_agent.app.main import (
    compile_resume,
    create_app,
    document_detail,
    documents,
    health,
    ingest_jd,
    ingest_questions,
    ingest_resume,
    resume_compile_log,
    resume_pdf,
    resume_source,
    save_resume_source,
    workspace_overview,
)
from interview_agent.app.schemas import (
    JDIngestRequest,
    QuestionIngestRequest,
    ResumeIngestRequest,
    ResumeSourceUpdateRequest,
)
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


def _seed_basic_workspace(request: SimpleNamespace) -> dict[str, str]:
    resume = _run(
        ingest_resume(
            request,
            ResumeIngestRequest(
                filename="resume.md",
                text="项目经历：做过 Redis 缓存、RAG 系统和 Agent 工作流。",
            ),
        )
    )
    jd = _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd.txt",
                company="ByteDance",
                role="Backend Intern",
                text="熟悉 Redis、MySQL 和高并发系统设计，具备良好的项目表达能力。",
            ),
        )
    )
    questions = _run(
        ingest_questions(
            request,
            QuestionIngestRequest(
                filename="questions.txt",
                text="Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作，然后用了 IO 多路复用。",
            ),
        )
    )
    return {
        "resume_id": resume.document_id,
        "jd_id": jd.document_id,
        "question_id": questions.document_id,
    }


def test_health_response(monkeypatch, tmp_path) -> None:
    _ = _make_request(monkeypatch, tmp_path)

    response = _run(health())

    assert response.status == "ok"
    assert response.app_name == "Interview Copilot Agent"


def test_workspace_overview_empty_workspace(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    response = _run(workspace_overview(request))

    assert response.active_document_counts == {"resume": 0, "jd": 0, "question": 0}
    assert response.latest_overall_risk is None
    assert response.top_gaps == []
    assert response.today_plan.plan_id == ""
    assert response.today_plan.tasks == []
    assert response.ticktick_sync_mode == "dry_run"


def test_workspace_overview_with_seeded_data(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    seeded = _seed_basic_workspace(request)

    with request.app.state.container.db.session_scope() as session:
        request.app.state.container.diagnosis.analyze(
            session,
            user_id="u_demo",
            jd_id=None,
            limit=3,
            persist=True,
        )
        plan = request.app.state.container.planning.generate(
            session,
            user_id="u_demo",
            jd_id=None,
            gap_limit=3,
            day=None,
        )

    response = _run(workspace_overview(request))

    assert response.active_document_counts == {"resume": 1, "jd": 1, "question": 1}
    assert response.latest_overall_risk in {"low", "medium", "high"}
    assert len(response.top_gaps) >= 1
    assert response.today_plan.plan_id == plan.plan_id
    assert len(response.today_plan.tasks) >= 1
    assert seeded["resume_id"]


def test_documents_filtering_and_inactive_records(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    _run(
        save_resume_source(
            request,
            ResumeSourceUpdateRequest(source="版本一：Redis"),
        )
    )
    _run(
        save_resume_source(
            request,
            ResumeSourceUpdateRequest(source="版本二：MySQL"),
        )
    )
    _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd.txt",
                company="ByteDance",
                role="Backend Intern",
                text="熟悉 Redis、MySQL 和高并发系统设计。",
            ),
        )
    )

    active_only = _run(documents(request, source_type="resume"))
    all_resumes = _run(documents(request, source_type="resume", active_only=False, limit=10))

    assert len(active_only) == 1
    assert active_only[0].filename == "resume.tex"

    assert len(all_resumes) == 1
    assert all_resumes[0].filename == "resume.tex"
    assert all_resumes[0].is_active is True


def test_document_detail_and_not_found(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    seeded = _seed_basic_workspace(request)

    detail = _run(document_detail(request, seeded["resume_id"]))

    assert detail.document_id == seeded["resume_id"]
    assert detail.source_type == "resume"
    assert "Redis" in detail.raw_text_preview

    try:
        _run(document_detail(request, "doc_missing"))
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "not found" in str(exc.detail).lower()
    else:
        raise AssertionError("Expected document_detail to raise HTTPException for missing documents.")


def test_cors_allows_browser_and_electron_origins(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    cors_middleware = next(
        middleware
        for middleware in request.app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs["allow_origins"] == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "null",
    ]


def test_resume_source_seeded_for_fresh_workspace(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    response = _run(resume_source(request))

    assert "\\documentclass" in response.source
    assert response.last_resume_document_id is None
    assert response.last_compile_status == "not_run"
    assert response.pdf_exists is False


def test_resume_source_save_replaces_prior_representation(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    _run(save_resume_source(request, ResumeSourceUpdateRequest(source="版本一：Redis")))
    saved = _run(save_resume_source(request, ResumeSourceUpdateRequest(source="版本二：MySQL")))

    assert saved.last_resume_document_id
    with request.app.state.container.db.session_scope() as session:
        docs = request.app.state.container.repository.list_documents(
            session,
            user_id="u_demo",
            source_type="resume",
            active_only=False,
            limit=10,
        )
        assert len(docs) == 1
        assert docs[0].id == saved.last_resume_document_id
        redis_matches = request.app.state.container.repository.lexical_search(
            session,
            user_id="u_demo",
            query_text="Redis",
            source_types=["resume"],
            limit=5,
        )
        assert redis_matches == []
        mysql_matches = request.app.state.container.repository.lexical_search(
            session,
            user_id="u_demo",
            query_text="MySQL",
            source_types=["resume"],
            limit=5,
        )
        assert len(mysql_matches) >= 1


def test_resume_compile_missing_compiler_returns_structured_error(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    service = request.app.state.container.resume_workspace
    monkeypatch.setattr(service, "_resolve_compiler_path", lambda: None)

    response = _run(compile_resume(request))

    assert response.last_compile_status == "missing_compiler"
    assert "Tectonic" in (response.last_compile_error_summary or "")
    log_text = _run(resume_compile_log(request))
    assert "Tectonic" in log_text.body.decode("utf-8")


def test_resume_pdf_not_found_before_compile(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    try:
        _run(resume_pdf(request))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected resume_pdf to raise HTTPException before the first compile.")
