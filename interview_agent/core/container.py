from __future__ import annotations

from dataclasses import dataclass

from interview_agent.actions.ticktick import TickTickClient, build_ticktick_client
from interview_agent.agent.context import AgentContextBuilder
from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.lifecycle import TurnLifecycle
from interview_agent.agent.plugins import PluginManager
from interview_agent.agent.proactive import DriftRunner, ProactiveTickService
from interview_agent.agent.events import ProactiveTickCompletedEvent, TurnCommittedEvent
from interview_agent.agent.memory import AgentMemoryStore, MemoryLifecycleHandler
from interview_agent.agent.reasoner import AgentReasoner
from interview_agent.agent.semantic_plugin import SemanticMemoryPlugin
from interview_agent.agent.runtime import InterviewAgentRuntime
from interview_agent.agent.tools import (
    AnalyzeGapTool,
    PlanTodayTool,
    RecallMemoryTool,
    SearchEvidenceTool,
    SyncTickTickTool,
    ToolRegistry,
)
from interview_agent.app.config import AppSettings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.diagnosis.service import GapAnalysisService
from interview_agent.ingestion.service import DocumentIngestionService, QuestionIngestionService
from interview_agent.memory2.memorizer import SemanticMemorizer
from interview_agent.memory2.retriever import SemanticMemoryRetriever
from interview_agent.memory2.store import SemanticMemoryStore
from interview_agent.mock.service import MockInterviewService
from interview_agent.planning.service import PlanService
from interview_agent.resume.service import ResumeWorkspaceService
from interview_agent.retrieval.service import RetrievalService
from interview_agent.storage.database import DatabaseManager
from interview_agent.storage.repositories import InterviewRepository
from interview_agent.storage.vector_store import ChromaVectorStore


@dataclass(slots=True)
class AppContainer:
    settings: AppSettings
    db: DatabaseManager
    provider: OpenAICompatibleProvider
    vector_store: ChromaVectorStore
    repository: InterviewRepository
    document_ingestion: DocumentIngestionService
    question_ingestion: QuestionIngestionService
    retrieval: RetrievalService
    diagnosis: GapAnalysisService
    planning: PlanService
    mock_interview: MockInterviewService
    resume_workspace: ResumeWorkspaceService
    ticktick: TickTickClient
    agent_event_bus: EventBus
    agent_memory: AgentMemoryStore
    agent_context: AgentContextBuilder
    agent_reasoner: AgentReasoner
    agent_runtime: InterviewAgentRuntime
    semantic_memory_store: SemanticMemoryStore
    semantic_memory_retriever: SemanticMemoryRetriever
    semantic_memorizer: SemanticMemorizer
    agent_tools: ToolRegistry
    proactive_service: ProactiveTickService

    @classmethod
    def build(cls, settings: AppSettings) -> "AppContainer":
        db = DatabaseManager(settings.resolved_database_url)
        provider = OpenAICompatibleProvider(settings=settings)
        vector_store = ChromaVectorStore(settings, provider)
        repository = InterviewRepository()
        retrieval = RetrievalService(repository=repository, vector_store=vector_store)
        document_ingestion = DocumentIngestionService(
            settings=settings,
            repository=repository,
            vector_store=vector_store,
        )
        question_ingestion = QuestionIngestionService(
            settings=settings,
            repository=repository,
            vector_store=vector_store,
            provider=provider,
        )
        diagnosis = GapAnalysisService(
            repository=repository,
            retrieval=retrieval,
            vector_store=vector_store,
        )
        resume_workspace = ResumeWorkspaceService(
            settings=settings,
            document_ingestion=document_ingestion,
        )
        ticktick = build_ticktick_client(settings)
        planning = PlanService(
            repository=repository,
            diagnosis=diagnosis,
            ticktick=ticktick,
        )
        mock_interview = MockInterviewService(
            repository=repository,
            retrieval=retrieval,
            diagnosis=diagnosis,
            question_ingestion=question_ingestion,
        )
        agent_event_bus = EventBus()
        lifecycle = TurnLifecycle(agent_event_bus)
        agent_memory = AgentMemoryStore(settings.memory_path)
        agent_context = AgentContextBuilder(repository)
        semantic_memory_store = SemanticMemoryStore(
            repository=repository,
            vector_store=vector_store,
        )
        semantic_memory_retriever = SemanticMemoryRetriever(
            store=semantic_memory_store,
            vector_store=vector_store,
        )
        semantic_memorizer = SemanticMemorizer(store=semantic_memory_store)
        agent_tools = ToolRegistry(
            [
                RecallMemoryTool(semantic_memory_retriever),
                SearchEvidenceTool(retrieval),
                AnalyzeGapTool(diagnosis),
                PlanTodayTool(planning),
                SyncTickTickTool(planning),
            ]
        )
        agent_reasoner = AgentReasoner(
            settings=settings,
            provider=provider,
            context_builder=agent_context,
        )
        memory_handler = MemoryLifecycleHandler(agent_memory)
        agent_event_bus.on(TurnCommittedEvent, memory_handler.handle_turn_committed)
        agent_event_bus.on(ProactiveTickCompletedEvent, memory_handler.handle_proactive_tick_completed)
        plugin_manager = PluginManager(
            plugins=[
                SemanticMemoryPlugin(
                    retriever=semantic_memory_retriever,
                    memorizer=semantic_memorizer,
                )
            ]
        )
        plugin_manager.bind(lifecycle)
        agent_runtime = InterviewAgentRuntime(
            reasoner=agent_reasoner,
            memory_store=agent_memory,
            event_bus=agent_event_bus,
            tool_registry=agent_tools,
            plugin_manager=plugin_manager,
        )
        proactive_service = ProactiveTickService(
            diagnosis=diagnosis,
            planning=planning,
            memory_store=agent_memory,
            drift_runner=DriftRunner(),
            event_bus=agent_event_bus,
            plugin_manager=plugin_manager,
            repository=repository,
        )
        db.create_all()
        with db.session_scope() as session:
            repository.rebuild_retrieval_fts(session)
        return cls(
            settings=settings,
            db=db,
            provider=provider,
            vector_store=vector_store,
            repository=repository,
            document_ingestion=document_ingestion,
            question_ingestion=question_ingestion,
            retrieval=retrieval,
            diagnosis=diagnosis,
            planning=planning,
            mock_interview=mock_interview,
            resume_workspace=resume_workspace,
            ticktick=ticktick,
            agent_event_bus=agent_event_bus,
            agent_memory=agent_memory,
            agent_context=agent_context,
            agent_reasoner=agent_reasoner,
            agent_runtime=agent_runtime,
            semantic_memory_store=semantic_memory_store,
            semantic_memory_retriever=semantic_memory_retriever,
            semantic_memorizer=semantic_memorizer,
            agent_tools=agent_tools,
            proactive_service=proactive_service,
        )
