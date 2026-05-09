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
    def _mock_chat(self, *, system_prompt: str, **_) -> str:
        if "面试题库结构化助手" in system_prompt:
            return (
                '{"questions":[{"question":"MySQL 的索引为什么用 B+ 树？",'
                '"answer":"因为范围查询友好。",'
                '"source_company":"ByteDance",'
                '"source_role":"Backend Intern",'
                '"dimension":"backend_basic",'
                '"topics":["MySQL"],'
                '"reference_answer":"回答应覆盖：B+ 树范围查询、叶子节点链表和树高。"}]}'
            )
        return (
            '{"reference_answer":"B+ 树更适合数据库索引，因为它降低树高、提升磁盘页利用率，'
            '并且叶子节点链表天然支持范围查询。",'
            '"mastery_level":"部分掌握",'
            '"gaps":["只提到了范围查询，缺少树高和磁盘页利用率。"],'
            '"next_probe":["为什么叶子节点链表对范围查询重要？"]}'
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "chat", _mock_chat)

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
        assert result.records[0]["mastery_level"] == "部分掌握"
        assert "磁盘页利用率" in result.records[0]["reference_answer"]


def test_question_ingestion_corrects_llm_backend_dimension_for_llm_topics(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path, enable_llm=True)

    def _mock_chat(self, *, system_prompt: str, **_) -> str:
        if "面试题库结构化助手" in system_prompt:
            return (
                '{"questions":[{"question":"kv cache 是什么，为什么能显著提升大模型推理吞吐？",'
                '"answer":"它缓存历史 token 的 key value，避免重复计算。",'
                '"source_company":"DeepSeek",'
                '"source_role":"LLM Infra Intern",'
                '"dimension":"backend_basic",'
                '"topics":["LLM基础","推理优化"],'
                '"reference_answer":"回答应覆盖：缓存历史 token、减少重复 attention 计算、'
                'prefill/decode 阶段差异和显存吞吐权衡。"}]}'
            )
        return (
            '{"reference_answer":"KV Cache 会缓存历史 token 的 K/V，避免每轮 decode 重算注意力，'
            '从而显著降低推理开销并提升吞吐。",'
            '"mastery_level":"部分掌握",'
            '"gaps":["缺少 prefill / decode 阶段差异。"],'
            '"next_probe":["KV Cache 为什么会增加显存占用？"]}'
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "chat", _mock_chat)

    with container.db.session_scope() as session:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="任意原文",
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "llm-pack"},
            source_company=None,
            source_role=None,
        )

        assert result.fallback_used is False
        assert result.records[0]["dimension"] == "llm_inference_serving"
        assert "LLM基础" in result.records[0]["topics"]


def test_question_ingestion_refines_generic_rag_llm_dimension(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path, enable_llm=True)

    def _mock_chat(self, *, system_prompt: str, **_) -> str:
        if "面试题库结构化助手" in system_prompt:
            return (
                '{"questions":[{"question":"LoRA 和 QLoRA 的核心区别是什么？",'
                '"answer":"QLoRA 额外结合了量化。",'
                '"source_company":"DeepSeek",'
                '"source_role":"LLM Infra Intern",'
                '"dimension":"rag_llm",'
                '"topics":["微调对齐"],'
                '"reference_answer":"回答应覆盖：可训练参数范围、量化方式、显存占用和效果 trade-off。"}]}'
            )
        return (
            '{"reference_answer":"LoRA 通过低秩适配减少可训练参数，QLoRA 则进一步把基座模型量化，'
            '在更低显存下完成微调。",'
            '"mastery_level":"部分掌握",'
            '"gaps":["没有展开显存与精度 trade-off。"],'
            '"next_probe":["QLoRA 为什么更省显存？"]}'
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "chat", _mock_chat)

    with container.db.session_scope() as session:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="任意原文",
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "llm-pack"},
            source_company=None,
            source_role=None,
        )

        assert result.fallback_used is False
        assert result.records[0]["dimension"] == "post_training_alignment"


def test_question_ingestion_can_save_without_evaluation_and_evaluate_later(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path, enable_llm=True)
    chat_calls: list[str] = []

    def _mock_chat(self, *, system_prompt: str, **_) -> str:
        chat_calls.append(system_prompt)
        if "面试题库结构化助手" in system_prompt:
            return (
                '{"questions":[{"question":"Redis 为什么单线程还这么快？",'
                '"answer":"因为它是内存操作。",'
                '"source_company":"ByteDance",'
                '"source_role":"Backend Intern",'
                '"dimension":"backend_basic",'
                '"topics":["Redis"],'
                '"reference_answer":"回答应覆盖：内存操作快、单线程避免锁竞争、IO 多路复用、事件循环模型。"}]}'
            )
        return (
            '{"reference_answer":"Redis 快的核心在于内存访问、单线程减少锁竞争、'
            'IO 多路复用和事件循环。",'
            '"mastery_level":"部分掌握",'
            '"gaps":["缺少单线程和事件循环。"],'
            '"next_probe":["为什么单线程并不一定慢？"],'
            '"accuracy_score":3,'
            '"structure_score":2,'
            '"depth_score":2,'
            '"score_summary":"你答到了结论的一部分，但关键原理没有展开。"}'
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "chat", _mock_chat)

    with container.db.session_scope() as session:
        saved = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="任意原文",
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "redis-pack"},
            source_company=None,
            source_role=None,
            evaluate_answers=False,
        )

        assert saved.records[0]["evaluation_status"] == "pending"
        assert saved.records[0]["accuracy_score"] is None
        assert len(chat_calls) == 1
        saved_document = container.repository.get_document(
            session,
            document_id=saved.ingested_document.document_id,
        )
        assert saved_document is not None
        assert saved_document.metadata_json["evaluation_status"] == "pending"
        assert saved_document.metadata_json["question_count"] == 1

        evaluated = container.question_ingestion.evaluate_question_document(
            session,
            user_id="u_demo",
            document_id=saved.ingested_document.document_id,
        )

        assert len(chat_calls) == 2
        assert evaluated.records[0]["evaluation_status"] == "completed"
        assert evaluated.records[0]["accuracy_score"] == 3
        assert evaluated.records[0]["score_summary"]
        evaluated_document = container.repository.get_document(
            session,
            document_id=saved.ingested_document.document_id,
        )
        assert evaluated_document is not None
        assert evaluated_document.metadata_json["evaluation_status"] == "completed"
        assert evaluated_document.metadata_json["source_company"] == "ByteDance"
        assert evaluated_document.metadata_json["source_role"] == "Backend Intern"
        assert evaluated_document.metadata_json["summary"]


def test_question_ingestion_falls_back_when_llm_evaluation_is_invalid(monkeypatch, tmp_path) -> None:
    container = _build_container(monkeypatch, tmp_path, enable_llm=True)

    def _mock_chat(self, *, system_prompt: str, **_) -> str:
        if "面试题库结构化助手" in system_prompt:
            return (
                '{"questions":[{"question":"Redis 为什么单线程还这么快？",'
                '"answer":"因为它是内存操作。",'
                '"source_company":"ByteDance",'
                '"source_role":"Backend Intern",'
                '"dimension":"backend_basic",'
                '"topics":["Redis"],'
                '"reference_answer":"回答应覆盖：内存操作快、单线程避免锁竞争、IO 多路复用、事件循环模型。"}]}'
            )
        return '{"reference_answer":"","mastery_level":"神级掌握","gaps":"bad","next_probe":[]}'

    monkeypatch.setattr(OpenAICompatibleProvider, "chat", _mock_chat)

    with container.db.session_scope() as session:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="任意原文",
            content_base64=None,
            filename="questions.txt",
            metadata={"source_key": "redis-pack"},
            source_company=None,
            source_role=None,
        )

        assert result.fallback_used is False
        assert result.records[0]["mastery_level"] == "需要加强"
        assert result.records[0]["gaps"]
        assert "事件循环模型" in result.records[0]["reference_answer"]


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
