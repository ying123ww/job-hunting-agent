from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from interview_agent.agent.runtime import AgentTurnRequest as RuntimeAgentTurnRequest
from interview_agent.actions.ticktick import SyncMode
from interview_agent.app.config import get_settings
from interview_agent.app.schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
    DocumentDetailResponse,
    DocumentSummaryResponse,
    GapAnalysisRequest,
    GapAnalysisResponse,
    HealthResponse,
    IngestResponse,
    JDIngestRequest,
    PlanGenerateRequest,
    PlanResponse,
    ProactiveTickRequest,
    ProactiveTickResponse,
    QuestionIngestRequest,
    QuestionIngestResponse,
    ResumeIngestRequest,
    SyncTickTickRequest,
    SyncTickTickResponse,
    TaskResponse,
    WorkspaceOverviewResponse,
)
from interview_agent.core.container import AppContainer


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = APIRouter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.container = AppContainer.build(settings)
    logger.info("Interview Copilot Agent initialized.")
    yield
    await app.state.container.agent_event_bus.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Interview Copilot Agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


def _container(request: Request) -> AppContainer:
    return request.app.state.container


def _user_id(container: AppContainer, requested: str | None) -> str:
    return requested or container.settings.default_user_id


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _task_response(task) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        title=task.title,
        dimension=task.dimension,
        priority=task.priority,
        due_at=task.due_at,
        duration_min=task.duration_min,
        status=task.status,
        reason=task.reason,
    )


def _gap_response(gap) -> dict[str, object]:
    if hasattr(gap, "gap_id"):
        evidence = [
            {
                "source_type": item.source_type,
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                "text": item.text,
                "score": item.score,
                "metadata_summary": item.metadata_summary,
            }
            for item in gap.evidence
        ]
        gap_id = gap.gap_id
    else:
        evidence = [
            {
                "source_type": str(item.get("source_type") or ""),
                "document_id": str(item.get("document_id") or ""),
                "chunk_id": str(item.get("chunk_id") or ""),
                "text": str(item.get("text") or ""),
                "score": float(item.get("score") or 0.0),
                "metadata_summary": dict(item.get("metadata_summary") or {}),
            }
            for item in (gap.evidence or [])
        ]
        gap_id = gap.id
    return {
        "gap_id": gap_id,
        "dimension": gap.dimension,
        "severity": gap.severity,
        "priority_score": gap.priority_score,
        "why_it_matters": gap.why_it_matters,
        "evidence": evidence,
        "repair_actions": gap.repair_actions,
    }


def _document_summary_response(document) -> DocumentSummaryResponse:
    return DocumentSummaryResponse(
        document_id=document.id,
        source_type=document.source_type,
        filename=document.filename,
        content_hash=document.content_hash,
        is_active=document.is_active,
        created_at=document.created_at,
        metadata=document.metadata_json or {},
    )


def _sync_mode(container: AppContainer) -> SyncMode:
    return "live" if container.settings.dida365_enabled else "dry_run"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", app_name=settings.app_name)


@router.get("/")
async def root() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "ingest_resume": "/ingest/resume",
            "ingest_jd": "/ingest/jd",
            "ingest_questions": "/ingest/questions",
            "diagnosis_gap": "/diagnosis/gap",
            "diagnosis_current": "/diagnosis/current",
            "plan_generate": "/plan/generate",
            "plan_today": "/plan/today",
            "plan_sync_ticktick": "/plan/sync_ticktick",
            "agent_turn": "/agent/turn",
            "agent_proactive_tick": "/agent/proactive/tick",
            "workspace_overview": "/workspace/overview",
            "documents": "/documents",
        },
    }


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.post("/ingest/resume", response_model=IngestResponse)
async def ingest_resume(http_request: Request, request: ResumeIngestRequest) -> IngestResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        result = container.document_ingestion.ingest_document(
            session,
            user_id=user_id,
            source_type="resume",
            text=request.text,
            content_base64=request.content_base64,
            filename=request.filename,
            metadata=request.metadata,
        )
        container.document_ingestion.persist_resume_side_effects(
            session,
            user_id=user_id,
            document_id=result.document_id,
            text=result.raw_text,
        )
        return IngestResponse(
            document_id=result.document_id,
            chunk_count=result.chunk_count,
            content_hash=result.content_hash,
            message="Resume ingested successfully.",
        )


@router.post("/ingest/jd", response_model=IngestResponse)
async def ingest_jd(http_request: Request, request: JDIngestRequest) -> IngestResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    metadata = {**request.metadata, "company": request.company, "role": request.role}
    with container.db.session_scope() as session:
        result = container.document_ingestion.ingest_document(
            session,
            user_id=user_id,
            source_type="jd",
            text=request.text,
            content_base64=request.content_base64,
            filename=request.filename,
            metadata=metadata,
        )
        container.document_ingestion.persist_jd_side_effects(
            session,
            user_id=user_id,
            document_id=result.document_id,
            text=result.raw_text,
            company=request.company,
            role=request.role,
        )
        return IngestResponse(
            document_id=result.document_id,
            chunk_count=result.chunk_count,
            content_hash=result.content_hash,
            message="JD ingested successfully.",
        )


@router.post("/ingest/questions", response_model=QuestionIngestResponse)
async def ingest_questions(http_request: Request, request: QuestionIngestRequest) -> QuestionIngestResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id=user_id,
            text=request.text,
            content_base64=request.content_base64,
            filename=request.filename,
            metadata=request.metadata,
            source_company=request.source_company,
            source_role=request.source_role,
        )
        top_gaps = [record["gaps"][0] for record in result.records[:3] if record["gaps"]]
        return QuestionIngestResponse(
            document_id=result.ingested_document.document_id,
            chunk_count=result.ingested_document.chunk_count,
            content_hash=result.ingested_document.content_hash,
            message="Questions ingested successfully.",
            processed_count=result.processed_count,
            deduped_count=len(result.records),
            skipped_count=result.skipped_count,
            inactive_count=result.inactive_count,
            fallback_used=result.fallback_used,
            pipeline_version=result.pipeline_version,
            top_gaps_found=top_gaps,
            records=result.records,
        )


@router.post("/diagnosis/gap", response_model=GapAnalysisResponse)
async def analyze_gap(http_request: Request, request: GapAnalysisRequest) -> GapAnalysisResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        overall_risk, gaps = container.diagnosis.analyze(
            session,
            user_id=user_id,
            jd_id=request.jd_id,
            limit=request.limit,
            persist=True,
        )
        return GapAnalysisResponse(
            overall_risk=overall_risk,
            generated_at=_utcnow(),
            top_gaps=[_gap_response(gap) for gap in gaps],
        )


@router.get("/diagnosis/current", response_model=GapAnalysisResponse)
async def current_gap(http_request: Request, user_id: str | None = None, limit: int = 3) -> GapAnalysisResponse:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        overall_risk, gaps = container.diagnosis.current(
            session,
            user_id=resolved_user_id,
            limit=limit,
        )
        return GapAnalysisResponse(
            overall_risk=overall_risk,
            generated_at=_utcnow(),
            top_gaps=[_gap_response(gap) for gap in gaps],
        )


@router.post("/plan/generate", response_model=PlanResponse)
async def generate_plan(http_request: Request, request: PlanGenerateRequest) -> PlanResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        plan = container.planning.generate(
            session,
            user_id=user_id,
            jd_id=request.jd_id,
            gap_limit=request.gap_limit,
            day=request.target_date,
        )
        return PlanResponse(
            plan_id=plan.plan_id,
            jd_id=plan.jd_id,
            summary=plan.summary,
            tasks=[_task_response(task) for task in plan.tasks],
        )


@router.get("/plan/today", response_model=PlanResponse)
async def today_plan(http_request: Request, user_id: str | None = None) -> PlanResponse:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        plan = container.planning.today(session, user_id=resolved_user_id, day=None)
        if plan is None:
            return PlanResponse(plan_id="", jd_id=None, summary="No plan for today.", tasks=[])
        return PlanResponse(
            plan_id=plan.plan_id,
            jd_id=plan.jd_id,
            summary=plan.summary,
            tasks=[_task_response(task) for task in plan.tasks],
        )


@router.post("/plan/sync_ticktick", response_model=SyncTickTickResponse)
async def sync_ticktick(http_request: Request, request: SyncTickTickRequest) -> SyncTickTickResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        summary = container.planning.sync_ticktick(
            session,
            user_id=user_id,
            plan_id=request.plan_id,
        )
        return SyncTickTickResponse(
            synced=summary.synced_count,
            mode=summary.mode,
            tasks=[_task_response(task) for task in summary.tasks],
        )


@router.get("/workspace/overview", response_model=WorkspaceOverviewResponse)
async def workspace_overview(http_request: Request, user_id: str | None = None) -> WorkspaceOverviewResponse:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        counts = container.repository.count_active_documents_by_source(
            session,
            user_id=resolved_user_id,
        )
        profile = container.repository.get_user_profile(session, user_id=resolved_user_id)
        gaps = container.repository.latest_gap_run(session, user_id=resolved_user_id, limit=3)
        today_plan_result = container.planning.today(session, user_id=resolved_user_id, day=None)
        if today_plan_result is None:
            today_plan = PlanResponse(
                plan_id="",
                jd_id=None,
                summary="No plan for today.",
                tasks=[],
            )
        else:
            today_plan = PlanResponse(
                plan_id=today_plan_result.plan_id,
                jd_id=today_plan_result.jd_id,
                summary=today_plan_result.summary,
                tasks=[_task_response(task) for task in today_plan_result.tasks],
            )
        return WorkspaceOverviewResponse(
            active_document_counts=counts,
            latest_overall_risk=profile.latest_overall_risk if profile is not None else None,
            top_gaps=[_gap_response(gap) for gap in gaps],
            today_plan=today_plan,
            ticktick_sync_mode=_sync_mode(container),
        )


@router.get("/documents", response_model=list[DocumentSummaryResponse])
async def documents(
    http_request: Request,
    user_id: str | None = None,
    source_type: str | None = None,
    active_only: bool = True,
    limit: int = 20,
) -> list[DocumentSummaryResponse]:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    normalized_source_type = source_type.strip() if source_type else None
    with container.db.session_scope() as session:
        items = container.repository.list_documents(
            session,
            user_id=resolved_user_id,
            source_type=normalized_source_type,
            active_only=active_only,
            limit=limit,
        )
        return [_document_summary_response(document) for document in items]


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
async def document_detail(http_request: Request, document_id: str) -> DocumentDetailResponse:
    container = _container(http_request)
    with container.db.session_scope() as session:
        document = container.repository.get_document(session, document_id=document_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"Document {document_id!r} was not found.")
        summary = _document_summary_response(document)
        return DocumentDetailResponse(
            **summary.model_dump(),
            raw_text_preview=document.raw_text[:4000],
        )


@router.post("/agent/turn", response_model=AgentTurnResponse)
async def agent_turn(http_request: Request, request: AgentTurnRequest) -> AgentTurnResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        result = await container.agent_runtime.run_turn(
            session,
            RuntimeAgentTurnRequest(
                user_id=user_id,
                message=request.message,
                jd_id=request.jd_id,
            ),
        )
        return AgentTurnResponse(
            turn_id=result.turn_id,
            intent=result.intent,
            reply=result.reply,
            current_jd_id=result.current_jd_id,
            generated_plan_id=result.generated_plan_id,
            evidence=[
                {
                    "source_type": item.source_type,
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                    "text": item.text,
                    "score": item.score,
                    "metadata_summary": item.metadata_summary,
                }
                for item in result.evidence
            ],
            lifecycle=result.lifecycle,
            memory_now=result.memory_now,
        )


@router.post("/agent/proactive/tick", response_model=ProactiveTickResponse)
async def proactive_tick(http_request: Request, request: ProactiveTickRequest) -> ProactiveTickResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        now_state = container.agent_memory.read_now_state()
        result = container.proactive_service.tick(
            session,
            user_id=user_id,
            current_jd_id=request.jd_id or now_state.get("current_jd_id") or None,
            force=request.force,
        )
        return ProactiveTickResponse(
            tick_id=result.tick_id,
            action=result.action,
            message=result.message,
            generated_plan_id=result.generated_plan_id,
            drift_entered=result.drift_entered,
        )


app = create_app()
