import asyncio
from datetime import datetime
from types import SimpleNamespace

from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import (
    AfterStepEvent,
    BeforeTurnEvent,
    ProactiveDriftCompletedEvent,
    ProactiveDriftStartedEvent,
    ProactiveTickCompletedEvent,
    ToolCallCompletedEvent,
)
from interview_agent.agent.memory import AgentMemoryStore, MemoryLifecycleHandler
from interview_agent.agent.plugins import PluginManager
from interview_agent.agent.proactive import DriftRunner, ProactiveTickService
from interview_agent.agent.reasoner import AgentTurnDecision
from interview_agent.agent.runtime import AgentTurnRequest, InterviewAgentRuntime
from interview_agent.agent.tools import ToolCall, ToolRegistry, ToolResult
from interview_agent.app.config import get_settings
from interview_agent.retrieval.service import RetrievalService
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
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
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
            url=None,
            job_description=None,
            job_requirements=None,
        )
        _question_result = container.question_ingestion.ingest_questions(
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
    assert (memory_dir / "WORKING_MEMORY.json").exists()
    assert "今天我该准备什么" in (memory_dir / "HISTORY.md").read_text(encoding="utf-8")
    assert "current_intent: plan" in (memory_dir / "NOW.md").read_text(encoding="utf-8")
    assert "current_goal" in (memory_dir / "NOW.md").read_text(encoding="utf-8")


def test_tool_loop_supports_step_plugins_and_error_events(tmp_path) -> None:
    class EchoTool:
        name = "echo"

        def run(self, ctx, arguments):
            return ToolResult(
                tool_name=self.name,
                status="ok",
                payload={"echo": arguments["message"]},
                preview=arguments["message"],
            )

    class BrokenTool:
        name = "broken"

        def run(self, ctx, arguments):
            raise RuntimeError("boom")

    class StepRewriteModule:
        async def run(self, frame):
            frame.slots["tool_call"].arguments["message"] = "patched-by-plugin"
            return frame

    class StepAuditModule:
        async def run(self, frame):
            frame.input.result.payload["audited"] = True
            return frame

    class StepPlugin:
        def bind(self, lifecycle) -> None:
            return None

        def before_step_modules_late(self):
            return (StepRewriteModule(),)

        def after_step_modules_early(self):
            return (StepAuditModule(),)

    class StubReasoner:
        def detect_intent(self, message: str) -> str:
            return "qa"

        def plan_tool_calls(self, *, message: str, intent: str):
            return [
                ToolCall(tool_name="echo", arguments={"message": "original"}),
                ToolCall(tool_name="broken", arguments={}),
            ]

        def finalize_turn(self, session, **kwargs):
            tool_results = kwargs["tool_results"]
            return AgentTurnDecision(
                intent="qa",
                reply=f"done:{tool_results[0].payload['echo']}",
                tool_results=tool_results,
            )

    bus = EventBus()
    completed_statuses: list[str] = []
    after_step_statuses: list[str] = []

    async def record_tool_completed(event: ToolCallCompletedEvent) -> None:
        completed_statuses.append(event.status)

    async def record_after_step(event: AfterStepEvent) -> None:
        after_step_statuses.append(event.status)

    bus.on(ToolCallCompletedEvent, record_tool_completed)
    bus.on(AfterStepEvent, record_after_step)

    runtime = InterviewAgentRuntime(
        reasoner=StubReasoner(),
        memory_store=AgentMemoryStore(tmp_path / "memory"),
        event_bus=bus,
        tool_registry=ToolRegistry([EchoTool(), BrokenTool()]),
        plugin_manager=PluginManager([StepPlugin()]),
    )

    result = asyncio.run(
        runtime.run_turn(
            None,
            AgentTurnRequest(
                user_id="u_demo",
                message="run tools",
                jd_id=None,
            ),
        )
    )

    assert result.reply == "done:patched-by-plugin"
    assert result.tool_results[0].payload["audited"] is True
    assert result.tool_results[1].status == "error"
    assert completed_statuses == ["ok", "error"]
    assert after_step_statuses == ["ok", "error"]


def test_tool_loop_can_replan_after_each_step(tmp_path) -> None:
    class FirstTool:
        name = "first"

        def run(self, ctx, arguments):
            return ToolResult(
                tool_name=self.name,
                status="ok",
                payload={"needs_followup": True},
                preview="first complete",
            )

    class SecondTool:
        name = "second"

        def run(self, ctx, arguments):
            return ToolResult(
                tool_name=self.name,
                status="ok",
                payload={"done": True},
                preview="second complete",
            )

    class ReflectiveReasoner:
        def detect_intent(self, message: str) -> str:
            return "qa"

        def max_tool_iterations(self, intent: str) -> int:
            return 3

        def plan_tool_calls(self, *, message: str, intent: str, previous_results=None):
            if previous_results:
                return []
            return [ToolCall(tool_name="first", arguments={})]

        def reflect_tool_results(self, *, message: str, intent: str, tool_results):
            if len(tool_results) == 1 and tool_results[0].payload.get("needs_followup"):
                return [ToolCall(tool_name="second", arguments={})]
            return []

        def finalize_turn(self, session, **kwargs):
            tool_results = kwargs["tool_results"]
            return AgentTurnDecision(
                intent="qa",
                reply=" -> ".join(result.tool_name for result in tool_results),
                tool_results=tool_results,
            )

    runtime = InterviewAgentRuntime(
        reasoner=ReflectiveReasoner(),
        memory_store=AgentMemoryStore(tmp_path / "memory"),
        event_bus=EventBus(),
        tool_registry=ToolRegistry([FirstTool(), SecondTool()]),
        plugin_manager=PluginManager([]),
    )

    result = asyncio.run(
        runtime.run_turn(
            None,
            AgentTurnRequest(
                user_id="u_demo",
                message="multi step",
                jd_id=None,
            ),
        )
    )

    assert result.reply == "first -> second"
    assert [item.tool_name for item in result.tool_results] == ["first", "second"]


def test_retrieval_route_uses_working_memory_state(tmp_path) -> None:
    memory_store = AgentMemoryStore(tmp_path / "memory")
    working = memory_store.read_working_memory()
    working.current_goal = "准备后端一面"
    working.latest_top_gap_dimensions = ["system_design"]
    memory_store.write_working_memory(working)

    snapshot = memory_store.snapshot()
    retrieval = RetrievalService(repository=None, vector_store=None)  # type: ignore[arg-type]
    route = retrieval.route_request(
        query_text="今天该学什么？",
        intent="plan",
        memory_snapshot=snapshot,
    )

    assert route.source_types == ["gap_record", "question", "jd", "resume"]
    assert route.dimension == "system_design"
    assert "准备后端一面" in route.query_text


def test_reasoner_qa_planner_uses_goal_and_source_hints(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
    get_settings.cache_clear()

    container = AppContainer.build(get_settings())
    working = container.agent_memory.read_working_memory()
    working.current_goal = "准备后端一面"
    working.latest_top_gap_dimensions = ["backend_basic"]
    container.agent_memory.write_working_memory(working)

    calls = container.agent_reasoner.plan_tool_calls(
        message="帮我看看这段简历项目怎么讲",
        intent="qa",
        current_jd_id="jd_test",
        memory_snapshot=container.agent_memory.snapshot(),
        previous_results=[
            ToolResult(
                tool_name="recall_memory",
                status="ok",
                payload={"hits": []},
                preview="none",
            )
        ],
    )

    assert len(calls) == 1
    assert calls[0].tool_name == "search_evidence"
    assert calls[0].arguments["dimension"] == "backend_basic"
    assert calls[0].arguments["source_types"] == ["resume", "jd"]
    assert "当前目标：准备后端一面" in calls[0].arguments["query"]


def test_proactive_tick_supports_drift_phase_plugins_and_updates_memory(tmp_path) -> None:
    class EmptyDiagnosis:
        def current(self, session, *, user_id: str, jd_id: str | None, limit: int):
            return "low", []

    class EmptyPlanning:
        def today(self, session, *, user_id: str, jd_id: str | None, day):
            return None

        def generate(self, session, *, user_id: str, jd_id, gap_limit: int, day):
            raise AssertionError("generate should not be called in drift path")

    class RecentContextModule:
        async def run(self, frame):
            frame.slots["recent_context"] = "# RECENT_CONTEXT\n\n- plugin injected context\n"
            return frame

    class ProactivePlugin:
        def bind(self, lifecycle) -> None:
            return None

        def proactive_before_tick_modules_late(self):
            return (RecentContextModule(),)

    memory_store = AgentMemoryStore(tmp_path / "memory")
    bus = EventBus()
    handler = MemoryLifecycleHandler(memory_store)
    bus.on(ProactiveTickCompletedEvent, handler.handle_proactive_tick_completed)
    drift_started: list[str] = []
    drift_completed: list[str] = []

    async def on_drift_started(event: ProactiveDriftStartedEvent) -> None:
        drift_started.append(event.tick_id)

    async def on_drift_completed(event: ProactiveDriftCompletedEvent) -> None:
        drift_completed.append(event.message)

    bus.on(ProactiveDriftStartedEvent, on_drift_started)
    bus.on(ProactiveDriftCompletedEvent, on_drift_completed)

    service = ProactiveTickService(
        diagnosis=EmptyDiagnosis(),
        planning=EmptyPlanning(),
        memory_store=memory_store,
        drift_runner=DriftRunner(),
        event_bus=bus,
        plugin_manager=PluginManager([ProactivePlugin()]),
    )

    result = service.tick(None, user_id="u_demo", current_jd_id=None, force=True)

    assert result.action == "drift"
    assert result.drift_entered is True
    assert result.lifecycle == ["ProactiveBeforeTick", "ProactiveStateMachine", "ProactiveDrift", "ProactiveAfterTick"]
    assert "最近上下文" in result.message
    assert len(drift_started) == 1
    assert drift_completed == [result.message]
    assert "proactive:drift" in (tmp_path / "memory" / "NOW.md").read_text(encoding="utf-8")


def test_semantic_memory_persists_turn_and_proactive_summaries(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
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
            url=None,
            job_description=None,
            job_requirements=None,
        )
        _question_result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。",
            content_base64=None,
            filename="questions.txt",
            metadata={},
            source_company=None,
            source_role=None,
        )

        _ = asyncio.run(
            container.agent_runtime.run_turn(
                session,
                AgentTurnRequest(
                    user_id="u_demo",
                    message="今天我该准备什么？",
                    jd_id=None,
                ),
            )
        )
        _ = container.proactive_service.tick(session, user_id="u_demo", current_jd_id=None, force=True)
        memory_items = container.semantic_memory_store.list_recent_memory(session, user_id="u_demo", limit=20)
        hits = container.semantic_memory_retriever.retrieve(
            session,
            user_id="u_demo",
            query="proactive 提醒 计划",
            limit=10,
        )

    summaries = [item.summary for item in memory_items]
    assert any("intent=plan" in summary for summary in summaries)
    assert any("proactive action=" in summary for summary in summaries)
    assert any("proactive action=" in hit.summary for hit in hits)


def test_proactive_tick_respects_do_not_disturb_policy(tmp_path) -> None:
    class EmptyDiagnosis:
        def current(self, session, *, user_id: str, jd_id: str | None, limit: int):
            return "medium", []

    class PlanningWithTask:
        def today(self, session, *, user_id: str, jd_id: str | None, day):
            return SimpleNamespace(
                plan_id="plan_1",
                tasks=[
                    SimpleNamespace(
                        title="复习 Redis",
                        duration_min=25,
                        reason="数据库基础仍需加强",
                        priority=3,
                    )
                ],
            )

        def generate(self, session, *, user_id: str, jd_id, gap_limit: int, day):
            raise AssertionError("generate should not be called")

    class RepoStub:
        def get_user_profile(self, session, *, user_id: str):
            return SimpleNamespace(
                learning_preference={
                    "proactive_enabled": True,
                    "do_not_disturb_start": "22:00",
                    "do_not_disturb_end": "08:00",
                    "reminder_time": "21:00",
                }
            )

    service = ProactiveTickService(
        diagnosis=EmptyDiagnosis(),
        planning=PlanningWithTask(),
        memory_store=AgentMemoryStore(tmp_path / "memory"),
        drift_runner=DriftRunner(),
        event_bus=EventBus(),
        plugin_manager=PluginManager([]),
        repository=RepoStub(),
        now_fn=lambda: datetime(2026, 5, 6, 23, 30),
    )

    result = service.tick(None, user_id="u_demo", current_jd_id=None, force=False)

    assert result.action == "skip"
    assert "免打扰" in result.message
    assert result.lifecycle == ["ProactiveBeforeTick", "ProactiveStateMachine", "ProactiveAfterTick"]


def test_proactive_tick_urgent_signal_bypasses_cooldown(tmp_path) -> None:
    class HighRiskDiagnosis:
        def current(self, session, *, user_id: str, jd_id: str | None, limit: int):
            return "high", [SimpleNamespace(dimension="system_design", severity="high")]

    class EmptyPlanning:
        def today(self, session, *, user_id: str, jd_id: str | None, day):
            return None

        def generate(self, session, *, user_id: str, jd_id, gap_limit: int, day):
            return SimpleNamespace(plan_id="plan_generated")

    class RepoStub:
        def get_user_profile(self, session, *, user_id: str):
            return SimpleNamespace(
                learning_preference={
                    "proactive_enabled": True,
                    "do_not_disturb_start": "23:00",
                    "do_not_disturb_end": "08:00",
                    "reminder_time": "21:00",
                    "cooldown_hours": 12,
                    "max_reminders_per_day": 1,
                }
            )

    memory_store = AgentMemoryStore(tmp_path / "memory")
    working = memory_store.read_working_memory()
    working.last_proactive_at = "2026-05-06T21:30:00"
    working.last_proactive_action = "reply"
    memory_store.write_working_memory(working)

    service = ProactiveTickService(
        diagnosis=HighRiskDiagnosis(),
        planning=EmptyPlanning(),
        memory_store=memory_store,
        drift_runner=DriftRunner(),
        event_bus=EventBus(),
        plugin_manager=PluginManager([]),
        repository=RepoStub(),
        now_fn=lambda: datetime(2026, 5, 6, 22, 0),
    )

    result = service.tick(None, user_id="u_demo", current_jd_id=None, force=False)

    assert result.action == "reply"
    assert result.generated_plan_id == "plan_generated"
    assert "system_design" in result.message


def test_proactive_tick_cooldown_blocks_non_urgent_reminders(tmp_path) -> None:
    class MediumDiagnosis:
        def current(self, session, *, user_id: str, jd_id: str | None, limit: int):
            return "medium", []

    class PlanningWithTask:
        def today(self, session, *, user_id: str, jd_id: str | None, day):
            return SimpleNamespace(
                plan_id="plan_1",
                tasks=[
                    SimpleNamespace(
                        title="补一题 Redis",
                        duration_min=10,
                        reason="保持手感",
                        priority=4,
                    )
                ],
            )

        def generate(self, session, *, user_id: str, jd_id, gap_limit: int, day):
            raise AssertionError("generate should not be called")

    class RepoStub:
        def get_user_profile(self, session, *, user_id: str):
            return SimpleNamespace(
                learning_preference={
                    "proactive_enabled": True,
                    "do_not_disturb_start": "23:00",
                    "do_not_disturb_end": "08:00",
                    "reminder_time": "09:00",
                    "cooldown_hours": 30,
                    "max_reminders_per_day": 5,
                }
            )

    memory_store = AgentMemoryStore(tmp_path / "memory")
    working = memory_store.read_working_memory()
    working.last_proactive_at = "2026-05-06T21:30:00"
    working.last_proactive_action = "reply"
    memory_store.write_working_memory(working)

    service = ProactiveTickService(
        diagnosis=MediumDiagnosis(),
        planning=PlanningWithTask(),
        memory_store=memory_store,
        drift_runner=DriftRunner(),
        event_bus=EventBus(),
        plugin_manager=PluginManager([]),
        repository=RepoStub(),
        now_fn=lambda: datetime(2026, 5, 7, 10, 0),
    )

    result = service.tick(None, user_id="u_demo", current_jd_id=None, force=False)

    assert result.action == "skip"
    assert "上次主动提醒" in result.message or "还很近" in result.message


def test_context_builder_includes_structured_profile_and_working_memory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
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
        jd_doc = container.document_ingestion.ingest_document(
            session,
            user_id="u_demo",
            source_type="jd",
            text="熟悉 Redis 与高并发系统设计。",
            content_base64=None,
            filename="jd.txt",
            metadata={"company": "ByteDance", "role": "Backend Intern"},
        )
        jd = container.document_ingestion.persist_jd_side_effects(
            session,
            user_id="u_demo",
            document_id=jd_doc.document_id,
            text=jd_doc.raw_text,
            company="ByteDance",
            role="Backend Intern",
            url=None,
            job_description=None,
            job_requirements=None,
        )
        _question_result = container.question_ingestion.ingest_questions(
            session,
            user_id="u_demo",
            text="Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。",
            content_base64=None,
            filename="questions.txt",
            metadata={},
            source_company=None,
            source_role=None,
        )
        _overall_risk, gaps = container.diagnosis.analyze(
            session,
            user_id="u_demo",
            jd_id=jd.id,
            limit=3,
            persist=True,
        )
        snapshot = container.agent_memory.snapshot()
        context = container.agent_context.build(
            session,
            user_id="u_demo",
            current_jd_id=jd.id,
            memory_snapshot=snapshot,
            evidence=gaps[0].evidence,
        )

    assert "## Structured Profile" in context.memory_block
    assert "Backend Intern" in context.memory_block
    assert "ByteDance" in context.memory_block
    assert "## Working Memory" in context.memory_block
