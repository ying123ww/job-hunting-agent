from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from interview_agent.app.config import get_settings
from interview_agent.app.main import (
    compile_resume,
    current_gap,
    create_app,
    document_detail,
    documents,
    health,
    ingest_jd,
    ingest_questions,
    ingest_resume,
    list_jds,
    resume_tailor_draft,
    resume_compile_log,
    resume_pdf,
    resume_source,
    save_resume_source,
    set_current_jd,
    today_plan,
    workspace_overview,
)
from interview_agent.app.schemas import (
    CurrentJDUpdateRequest,
    JDIngestRequest,
    QuestionIngestRequest,
    ResumeIngestRequest,
    ResumeSourceUpdateRequest,
    ResumeTailorDraftRequest,
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
        current_jd = request.app.state.container.repository.resolve_target_jd(
            session,
            user_id="u_demo",
            requested_jd_id=None,
        )
        request.app.state.container.diagnosis.analyze(
            session,
            user_id="u_demo",
            jd_id=current_jd.id if current_jd is not None else None,
            limit=3,
            persist=True,
        )
        plan = request.app.state.container.planning.generate(
            session,
            user_id="u_demo",
            jd_id=current_jd.id if current_jd is not None else None,
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


def test_ingest_jd_preserves_structured_sections_in_metadata(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    created = _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd.txt",
                company="ByteDance",
                role="Backend Intern",
                job_description="负责后端服务开发，与产品和算法团队合作推进项目。",
                job_requirements="熟悉 Redis\n具备系统设计能力",
            ),
        )
    )

    detail = _run(document_detail(request, created.document_id))

    assert detail.metadata["job_description"] == "负责后端服务开发，与产品和算法团队合作推进项目。"
    assert detail.metadata["job_requirements"] == "熟悉 Redis\n具备系统设计能力"
    assert "职位描述" in detail.raw_text_preview
    assert "职位要求" in detail.raw_text_preview


def test_ingest_jd_promotes_url_and_sections_to_canonical_target(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    created = _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/backend-intern",
                job_description="负责后端服务开发，参与高并发链路优化。",
                job_requirements="熟悉 Redis\n熟悉 MySQL",
            ),
        )
    )

    with request.app.state.container.db.session_scope() as session:
        jds = request.app.state.container.repository.list_target_jds(session, user_id="u_demo")
        profile = request.app.state.container.repository.get_user_profile(session, user_id="u_demo")

    assert len(jds) == 1
    assert jds[0].document_id == created.document_id
    assert jds[0].url == "https://jobs.example.com/backend-intern"
    assert jds[0].job_description == "负责后端服务开发，参与高并发链路优化。"
    assert jds[0].job_requirements == "熟悉 Redis\n熟悉 MySQL"
    assert profile is not None
    assert profile.current_jd_id == jds[0].id


def test_list_jds_and_set_current_jd(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-1.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/jd-1",
                job_requirements="熟悉 Redis",
            ),
        )
    )
    _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-2.txt",
                company="Meituan",
                role="Backend Intern",
                url="https://jobs.example.com/jd-2",
                job_requirements="熟悉 高并发 系统设计",
            ),
        )
    )

    before_switch = _run(list_jds(request))

    assert len(before_switch) == 2
    assert before_switch[0].company == "Meituan"
    assert before_switch[0].is_current is True
    assert before_switch[1].is_current is False

    switched = _run(
        set_current_jd(
            request,
            CurrentJDUpdateRequest(jd_id=before_switch[1].jd_id),
        )
    )
    after_switch = _run(list_jds(request))

    assert switched.current_jd_id == before_switch[1].jd_id
    assert after_switch[0].jd_id == before_switch[0].jd_id
    assert after_switch[0].is_current is False
    assert after_switch[1].jd_id == before_switch[1].jd_id
    assert after_switch[1].is_current is True


def test_ingest_jd_same_url_supersedes_old_document_but_different_url_can_coexist(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)

    first = _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-1.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/backend-intern",
                text="熟悉 Redis",
            ),
        )
    )
    second = _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-2.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/backend-intern",
                text="熟悉 Redis 和 MySQL",
            ),
        )
    )
    third = _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-3.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/backend-intern-alt",
                text="熟悉 高并发 系统设计",
            ),
        )
    )

    with request.app.state.container.db.session_scope() as session:
        doc_first = request.app.state.container.repository.get_document(session, document_id=first.document_id)
        doc_second = request.app.state.container.repository.get_document(session, document_id=second.document_id)
        doc_third = request.app.state.container.repository.get_document(session, document_id=third.document_id)
        active_docs = request.app.state.container.repository.list_documents(
            session,
            user_id="u_demo",
            source_type="jd",
            active_only=True,
            limit=10,
        )

    assert doc_first is not None and doc_first.is_active is False
    assert doc_first.superseded_by == second.document_id
    assert doc_second is not None and doc_second.is_active is True
    assert doc_third is not None and doc_third.is_active is True
    assert {item.id for item in active_docs} == {second.document_id, third.document_id}


def test_current_jd_selection_scopes_gap_and_plan_routes(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    _seed_basic_workspace(request)

    _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-backend.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/backend",
                job_requirements="熟悉 Redis",
            ),
        )
    )
    _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd-design.txt",
                company="Meituan",
                role="Backend Intern",
                url="https://jobs.example.com/design",
                job_requirements="熟悉 高并发 系统设计",
            ),
        )
    )
    jd_records = _run(list_jds(request))
    backend_jd = next(item for item in jd_records if item.company == "ByteDance" and item.url == "https://jobs.example.com/backend")
    design_jd = next(item for item in jd_records if item.company == "Meituan")

    with request.app.state.container.db.session_scope() as session:
        request.app.state.container.diagnosis.analyze(
            session,
            user_id="u_demo",
            jd_id=backend_jd.jd_id,
            limit=3,
            persist=True,
        )
        backend_plan = request.app.state.container.planning.generate(
            session,
            user_id="u_demo",
            jd_id=backend_jd.jd_id,
            gap_limit=3,
            day=None,
        )
        request.app.state.container.diagnosis.analyze(
            session,
            user_id="u_demo",
            jd_id=design_jd.jd_id,
            limit=3,
            persist=True,
        )
        design_plan = request.app.state.container.planning.generate(
            session,
            user_id="u_demo",
            jd_id=design_jd.jd_id,
            gap_limit=3,
            day=None,
        )

    _run(set_current_jd(request, CurrentJDUpdateRequest(jd_id=backend_jd.jd_id)))
    backend_gap = _run(current_gap(request))
    backend_today = _run(today_plan(request))

    _run(set_current_jd(request, CurrentJDUpdateRequest(jd_id=design_jd.jd_id)))
    design_gap = _run(current_gap(request))
    design_today = _run(today_plan(request))

    assert backend_gap.jd_id == backend_jd.jd_id
    assert backend_gap.top_gaps
    assert "目标 JD 明确强调" in backend_gap.top_gaps[0].why_it_matters
    assert backend_today.jd_id == backend_jd.jd_id
    assert backend_today.plan_id == backend_plan.plan_id

    assert design_gap.jd_id == design_jd.jd_id
    assert design_gap.top_gaps
    assert "目标 JD 明确强调" not in design_gap.top_gaps[0].why_it_matters
    assert design_today.jd_id == design_jd.jd_id
    assert design_today.plan_id == design_plan.plan_id


def test_resume_tailor_draft_returns_jd_aware_suggestions_without_mutating_resume(monkeypatch, tmp_path) -> None:
    request = _make_request(monkeypatch, tmp_path)
    _run(
        save_resume_source(
            request,
            ResumeSourceUpdateRequest(
                source="项目经历：做过 Redis 缓存系统，并优化了接口延迟。",
            ),
        )
    )
    _run(
        ingest_jd(
            request,
            JDIngestRequest(
                filename="jd.txt",
                company="ByteDance",
                role="Backend Intern",
                url="https://jobs.example.com/backend",
                job_requirements="熟悉 Redis\n熟悉 MySQL",
            ),
        )
    )

    before = _run(resume_source(request))
    draft = _run(resume_tailor_draft(request, ResumeTailorDraftRequest()))
    after = _run(resume_source(request))

    assert draft.jd_id
    assert "Redis" in draft.summary or "backend_basic" in draft.summary
    assert draft.highlighted_keywords
    assert len(draft.suggestions) >= 2
    assert before.source == after.source


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
