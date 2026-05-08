from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer


def test_end_to_end_service_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
    get_settings.cache_clear()

    container = AppContainer.build(get_settings())

    with container.db.session_scope() as session:
        resume = container.document_ingestion.ingest_document(
            session,
            user_id="u_demo",
            source_type="resume",
            text="项目经历：做过 Redis 缓存和 RAG 系统。",
            content_base64=None,
            filename="resume.md",
            metadata={},
        )
        container.document_ingestion.persist_resume_side_effects(
            session,
            user_id="u_demo",
            document_id=resume.document_id,
            text=resume.raw_text,
        )
        assert resume.document_id

        jd = container.document_ingestion.ingest_document(
            session,
            user_id="u_demo",
            source_type="jd",
            text="熟悉 Redis、MySQL 和高并发系统设计。",
            content_base64=None,
            filename="jd.txt",
            metadata={"company": "ByteDance", "role": "Backend Intern"},
        )
        container.document_ingestion.persist_jd_side_effects(
            session,
            user_id="u_demo",
            document_id=jd.document_id,
            text=jd.raw_text,
            company="ByteDance",
            role="Backend Intern",
            url=None,
            job_description=None,
            job_requirements=None,
        )

        question_result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。",
            content_base64=None,
            filename="questions.txt",
            metadata={},
            source_company=None,
            source_role=None,
        )
        assert question_result.ingested_document.document_id
        assert question_result.processed_count == 1
        assert len(question_result.records) == 1

        overall_risk, gaps = container.diagnosis.analyze(
            session,
            user_id="u_demo",
            jd_id=None,
            limit=3,
            persist=True,
        )
        assert overall_risk in {"low", "medium", "high"}
        assert gaps
        assert gaps[0].evidence
        profile = container.repository.get_user_profile(session, user_id="u_demo")
        assert profile is not None
        assert "ByteDance" in profile.target_companies
        assert "Backend Intern" in profile.target_roles
        assert profile.latest_overall_risk == overall_risk
        assert profile.weak_points

        plan = container.planning.generate(
            session,
            user_id="u_demo",
            jd_id=None,
            gap_limit=3,
            day=None,
        )
        assert plan.plan_id
        assert plan.tasks
