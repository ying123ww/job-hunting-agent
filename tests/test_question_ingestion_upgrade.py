from __future__ import annotations

from interview_agent.app.config import get_settings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.core.container import AppContainer
from interview_agent.retrieval.service import RetrievalService


class EmptyVectorStore:
    def query(self, *, collection_name: str, query_text: str, where, limit: int):
        return []


def _build_container(monkeypatch, tmp_path, *, enable_llm: bool = False) -> AppContainer:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("INTERVIEW_AGENT_EMBEDDING_API_KEY", "")
    if enable_llm:
        monkeypatch.setenv("INTERVIEW_AGENT_LLM_BASE_URL", "https://example.test")
        monkeypatch.setenv("INTERVIEW_AGENT_LLM_API_KEY", "secret")
    else:
        monkeypatch.setenv("INTERVIEW_AGENT_LLM_BASE_URL", "")
        monkeypatch.setenv("INTERVIEW_AGENT_LLM_API_KEY", "")
    monkeypatch.setattr(
        OpenAICompatibleProvider,
        "embed",
        lambda self, texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts],
    )
    get_settings.cache_clear()
    return AppContainer.build(get_settings())


def test_question_ingestion_falls_back_and_skips_intra_doc_duplicates(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path)

    with container.db.session_scope() as session:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text=(
                "Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。\n\n"
                "Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。"
            ),
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "mock-redis-pack"},
            source_company="ByteDance",
            source_role="Backend Intern",
        )

        assert result.fallback_used is True
        assert result.processed_count == 2
        assert result.skipped_count == 1
        assert len(result.records) == 1


def test_question_ingestion_uses_llm_payload_when_available(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path, enable_llm=True)
    monkeypatch.setattr(
        OpenAICompatibleProvider,
        "chat",
        lambda self, **_: (
            '{"questions":[{"question":"MySQL 的索引为什么用 B+ 树？",'
            '"answer":"因为范围查询友好。",'
            '"source_company":"ByteDance",'
            '"source_role":"Backend Intern",'
            '"dimension":"backend_basic",'
            '"topics":["MySQL"],'
            '"reference_answer":"回答应覆盖：B+ 树范围查询、叶子节点链表和树高。"}]}'
        ),
    )

    with container.db.session_scope() as session:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="任意原文",
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "mysql-pack"},
            source_company=None,
            source_role=None,
        )

        assert result.fallback_used is False
        assert result.processed_count == 1
        assert result.records[0]["question"] == "MySQL 的索引为什么用 B+ 树？"
        assert result.records[0]["topics"] == ["MySQL"]


def test_question_ingestion_supports_incremental_scope_updates(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path)

    with container.db.session_scope() as session:
        first = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text=(
                "Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。\n\n"
                "MySQL 的索引为什么用 B+ 树不用 B 树？\n我的答案：范围查询方便。"
            ),
            content_base64=None,
            filename="questions-v1.txt",
            metadata={"source_key": "backend-pack"},
            source_company="ByteDance",
            source_role="Backend Intern",
        )
        assert first.processed_count == 2
        assert len(first.records) == 2

        second = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作，还用了 IO 多路复用。",
            content_base64=None,
            filename="questions-v2.txt",
            metadata={"source_key": "backend-pack"},
            source_company="ByteDance",
            source_role="Backend Intern",
        )

        active_questions = container.repository.list_questions(session, user_id="u_demo")
        all_questions = container.repository.list_questions(session, user_id="u_demo", active_only=False)

        assert second.processed_count == 1
        assert second.inactive_count == 2
        assert len(active_questions) == 1
        assert len(all_questions) == 3

        removed_hits = container.repository.lexical_search(
            session,
            user_id="u_demo",
            query_text="B+ 树 范围查询",
            source_types=["question"],
            limit=5,
        )
        assert removed_hits == []


def test_hybrid_retrieval_can_use_fts_without_dense_hits(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path)

    with container.db.session_scope() as session:
        container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="MySQL 的索引为什么用 B+ 树不用 B 树？\n我的答案：范围查询方便。",
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "mysql-pack"},
            source_company="ByteDance",
            source_role="Backend Intern",
        )

        retrieval = RetrievalService(
            repository=container.repository,
            vector_store=EmptyVectorStore(),  # type: ignore[arg-type]
        )
        evidence = retrieval.build_evidence_bundle(
            session,
            user_id="u_demo",
            query_text="B+ 树 范围查询",
            source_types=["question"],
            limit=3,
        )

        assert evidence
        assert evidence[0].source_type == "question"
        assert "B+ 树" in evidence[0].text
