from __future__ import annotations

from dataclasses import dataclass

from interview_agent.actions.ticktick import StubTickTickClient
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
        )
