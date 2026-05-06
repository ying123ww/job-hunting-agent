import asyncio

from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import BeforeTurnEvent
from interview_agent.agent.runtime import AgentTurnRequest
from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer


def test_event_bus_emit_can_intercept() -> None:
    bus = EventBus()

    async def rewrite(event: BeforeTurnEvent) -> BeforeTurnEvent:
        event.current_jd_id = "jd_test"
        return event

    bus.on(BeforeTurnEvent, rewrite)
    event = asyncio.run(
        bus.emit(
            BeforeTurnEvent(
                user_id="u_demo",
                message="hello",
            )
        )
    )

    assert event.current_jd_id == "jd_test"


def test_agent_runtime_writes_markdown_memory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    get_settings.cache_clear()

    container = AppContainer.build(get_settings())

    with container.db.session_scope() as session:
        _ = container.document_ingestion.ingest_document(
            session,
            user_id="u_demo",
            source_type="resume",
            text="项目经历：做过 Redis 缓存系统。",
            content_base64=None,
            filename="resume.md",
            metadata={},
        )
        jd = container.document_ingestion.ingest_document(
            session,
            user_id="u_demo",
            source_type="jd",
            text="熟悉 Redis 与高并发系统设计。",
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
        )
        _doc, _records, _count = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。",
            content_base64=None,
            filename="questions.txt",
            metadata={},
            source_company=None,
            source_role=None,
        )

        result = asyncio.run(
            container.agent_runtime.run_turn(
                session,
                AgentTurnRequest(
                    user_id="u_demo",
                    message="今天我该准备什么？",
                    jd_id=None,
                ),
            )
        )

    assert result.intent == "plan"
    assert result.lifecycle == [
        "BeforeTurn",
        "BeforeReasoning",
        "AfterReasoning",
        "AfterTurn",
    ]
    memory_dir = tmp_path / "memory"
    assert (memory_dir / "MEMORY.md").exists()
    assert (memory_dir / "SELF.md").exists()
    assert (memory_dir / "HISTORY.md").exists()
    assert (memory_dir / "RECENT_CONTEXT.md").exists()
    assert (memory_dir / "PENDING.md").exists()
    assert (memory_dir / "NOW.md").exists()
    assert "今天我该准备什么" in (memory_dir / "HISTORY.md").read_text(encoding="utf-8")
    assert "current_intent: plan" in (memory_dir / "NOW.md").read_text(encoding="utf-8")
