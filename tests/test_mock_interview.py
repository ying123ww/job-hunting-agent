from __future__ import annotations

from pathlib import Path

import pytest

from interview_agent.app.config import get_settings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.core.container import AppContainer
from interview_agent.mock.service import SubmittedMockAnswer
from interview_agent.storage.repositories import InterviewRepository


USER_ID = "u_mock"


def _build_container(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AppContainer:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("INTERVIEW_AGENT_EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("INTERVIEW_AGENT_LLM_BASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_LLM_API_KEY", "")
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
    monkeypatch.setattr(OpenAICompatibleProvider, "embed", lambda self, texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    get_settings.cache_clear()
    return AppContainer.build(get_settings())


def _seed_question_bank(container: AppContainer, session, dimensions: list[str]) -> list[str]:
    repo: InterviewRepository = container.repository
    repo.ensure_user(session, USER_ID)
    document = repo.create_document(
        session,
        user_id=USER_ID,
        source_type="question",
        filename="mock_questions.txt",
        content_hash="mock-questions",
        raw_text="mock question bank",
        metadata_json={"source_scope": "mock-test"},
    )
    question_ids: list[str] = []
    for index, dimension in enumerate(dimensions, start=1):
        chunk = repo.create_document_chunk(
            session,
            document_id=document.id,
            user_id=USER_ID,
            source_type="question",
            chunk_index=index,
            text=f"{dimension} chunk {index}",
            metadata_json={"dimension": dimension},
            vector_collection="test",
            vector_id=None,
        )
        question = repo.create_question(
            session,
            user_id=USER_ID,
            document_id=document.id,
            source_chunk_id=chunk.id,
            text=f"{dimension} 面试题 {index}：请解释核心机制和项目落地方式？",
            source_company="EvalCorp",
            source_role="Backend Intern",
            dimension=dimension,
            topics=[dimension, f"topic-{index}"],
            reference_answer=f"回答应覆盖 {dimension} 的原理、边界、项目证据和结果。",
            normalized_text=f"{dimension}-question-{index}",
            question_fingerprint=f"{dimension}-fingerprint-{index}",
            source_scope="mock-test",
        )
        repo.create_answer_record(
            session,
            question_id=question.id,
            user_id=USER_ID,
            user_answer="只回答了概念，没有项目和边界。",
            mastery_level="需要加强",
            gaps=[f"{dimension} 缺少项目证据"],
            next_probe=[f"继续追问 {dimension}"],
        )
        repo.update_question_mastery(session, question_id=question.id, mastery_level="需要加强")
        question_ids.append(question.id)
    return question_ids


def _seed_jd(container: AppContainer, session) -> str:
    repo = container.repository
    repo.ensure_user(session, USER_ID)
    document = repo.create_document(
        session,
        user_id=USER_ID,
        source_type="jd",
        filename="jd.txt",
        content_hash="mock-jd",
        raw_text="需要熟悉 LLM 推理服务、RAG 检索和后端系统设计。",
        metadata_json={},
    )
    jd = repo.create_target_jd(
        session,
        user_id=USER_ID,
        document_id=document.id,
        company="EvalCorp",
        role="AI Backend Intern",
        url=None,
        job_description="做 AI 后端和评测平台。",
        job_requirements="熟悉 LLM 推理服务、RAG 检索和后端系统设计。",
        raw_text=document.raw_text,
        structured_requirements=[
            {"text": "熟悉 LLM 推理服务和 KV Cache", "dimension": "llm_inference_serving", "topics": ["KV Cache"], "weight": 0.9},
            {"text": "熟悉 RAG 检索和 evidence grounding", "dimension": "rag_retrieval", "topics": ["RAG"], "weight": 0.7},
            {"text": "具备后端系统设计经验", "dimension": "backend_basic", "topics": ["system design"], "weight": 0.5},
        ],
    )
    repo.upsert_user_profile(session, user_id=USER_ID, current_jd_id=jd.id)
    return jd.id


def test_global_mock_generates_twenty_and_writes_scores(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    container = _build_container(monkeypatch, tmp_path)
    with container.db.session_scope() as session:
        question_ids = _seed_question_bank(container, session, ["backend_basic"] * 20)

        view = container.mock_interview.create_session(
            session,
            user_id=USER_ID,
            mode="weakness_global",
            jd_id=None,
            target_dimension=None,
            question_count=20,
        )

        assert view.status == "in_progress"
        assert len(view.questions) == 20
        assert view.source_mix == {"original": 12, "variant": 8}
        assert len({question.prompt for question in view.questions}) == 20

        answered = container.mock_interview.submit_answers(
            session,
            user_id=USER_ID,
            session_id=view.session_id,
            answers=[
                SubmittedMockAnswer(
                    mock_question_id=question.mock_question_id,
                    user_answer="我会从原理、项目证据、边界和指标四部分回答。",
                )
                for question in view.questions
            ],
        )

        assert all(question.answer is not None for question in answered.questions)
        original_question = next(question for question in answered.questions if question.source_kind == "original")
        records = container.repository.list_answer_records_for_question(
            session,
            question_id=original_question.source_question_id or question_ids[0],
        )
        assert len(records) >= 2

        completed = container.mock_interview.complete_session(session, user_id=USER_ID, session_id=view.session_id)
        assert completed.status == "completed"
        assert completed.completed_at is not None
        assert "完成 20/20 题" in completed.summary


def test_dimension_mock_stays_within_target_dimension(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    container = _build_container(monkeypatch, tmp_path)
    with container.db.session_scope() as session:
        _seed_question_bank(container, session, ["rag_retrieval"] * 5 + ["backend_basic"] * 12)

        view = container.mock_interview.create_session(
            session,
            user_id=USER_ID,
            mode="weakness_dimension",
            jd_id=None,
            target_dimension="rag_retrieval",
            question_count=20,
        )

        assert len(view.questions) == 20
        assert {question.dimension for question in view.questions} == {"rag_retrieval"}
        assert view.source_mix == {"original": 5, "variant": 5, "generated": 10}


def test_jd_mock_uses_current_jd_requirements(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    container = _build_container(monkeypatch, tmp_path)
    with container.db.session_scope() as session:
        jd_id = _seed_jd(container, session)
        _seed_question_bank(
            container,
            session,
            ["llm_inference_serving", "rag_retrieval", "backend_basic", "backend_basic"],
        )

        view = container.mock_interview.create_session(
            session,
            user_id=USER_ID,
            mode="jd",
            jd_id=None,
            target_dimension=None,
            question_count=20,
        )

        assert view.jd_id == jd_id
        assert len(view.questions) == 20
        assert "llm_inference_serving" in {question.dimension for question in view.questions}
        assert "rag_retrieval" in {question.dimension for question in view.questions}
        assert view.source_mix["generated"] >= 1
