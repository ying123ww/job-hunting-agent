from __future__ import annotations

from dataclasses import dataclass

from interview_agent.actions.ticktick import StubTickTickClient
from interview_agent.agent.context import AgentContextBuilder
from interview_agent.agent.event_bus import EventBus
from interview_agent.agent.events import TurnCommittedEvent
from interview_agent.agent.memory import AgentMemoryStore, MemoryLifecycleHandler
from interview_agent.agent.reasoner import AgentReasoner
from interview_agent.agent.runtime import InterviewAgentRuntime
from interview_agent.app.config import AppSettings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.diagnosis.service import GapAnalysisService
from interview_agent.ingestion.service import DocumentIngestionService, QuestionIngestionService
from interview_agent.planning.service import PlanService
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
    ticktick: StubTickTickClient
    agent_event_bus: EventBus
    agent_memory: AgentMemoryStore
    agent_context: AgentContextBuilder
    agent_reasoner: AgentReasoner
    agent_runtime: InterviewAgentRuntime

    @classmethod
    def build(cls, settings: AppSettings) -> "AppContainer":
        db = DatabaseManager(settings.database_url)
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
        )
        diagnosis = GapAnalysisService(
            repository=repository,
            retrieval=retrieval,
            vector_store=vector_store,
        )
        ticktick = StubTickTickClient()
        planning = PlanService(
            repository=repository,
            diagnosis=diagnosis,
            ticktick=ticktick,
        )
        agent_event_bus = EventBus()
        agent_memory = AgentMemoryStore(settings.memory_path)
        agent_context = AgentContextBuilder(repository)
        agent_reasoner = AgentReasoner(
            settings=settings,
            provider=provider,
            context_builder=agent_context,
            retrieval=retrieval,
            diagnosis=diagnosis,
            planning=planning,
        )
        memory_handler = MemoryLifecycleHandler(agent_memory)
        agent_event_bus.on(TurnCommittedEvent, memory_handler.handle_turn_committed)
        agent_runtime = InterviewAgentRuntime(
            repository=repository,
            reasoner=agent_reasoner,
            memory_store=agent_memory,
            event_bus=agent_event_bus,
        )
        db.create_all()
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
            ticktick=ticktick,
            agent_event_bus=agent_event_bus,
            agent_memory=agent_memory,
            agent_context=agent_context,
            agent_reasoner=agent_reasoner,
            agent_runtime=agent_runtime,
        )
