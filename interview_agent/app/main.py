from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import Response

from interview_agent.agent.runtime import AgentTurnRequest as RuntimeAgentTurnRequest
from interview_agent.app.config import get_settings
from interview_agent.app.schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
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
)
from interview_agent.core.container import AppContainer


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.container = AppContainer.build(settings)
    logger.info("Interview Copilot Agent initialized.")
    yield
    await app.state.container.agent_event_bus.aclose()


app = FastAPI(title="Interview Copilot Agent", lifespan=lifespan)


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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", app_name=settings.app_name)


@app.get("/")
def root() -> dict[str, object]:
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
        },
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.post("/ingest/resume", response_model=IngestResponse)
def ingest_resume(request: ResumeIngestRequest) -> IngestResponse:
    container: AppContainer = app.state.container
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


@app.post("/ingest/jd", response_model=IngestResponse)
def ingest_jd(request: JDIngestRequest) -> IngestResponse:
    container: AppContainer = app.state.container
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


@app.post("/ingest/questions", response_model=QuestionIngestResponse)
def ingest_questions(request: QuestionIngestRequest) -> QuestionIngestResponse:
    container: AppContainer = app.state.container
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        result, records, raw_count = container.question_ingestion.ingest_questions(
            session,
            user_id=user_id,
            text=request.text,
            content_base64=request.content_base64,
            filename=request.filename,
            metadata=request.metadata,
            source_company=request.source_company,
            source_role=request.source_role,
        )
        top_gaps = [record["gaps"][0] for record in records[:3] if record["gaps"]]
        return QuestionIngestResponse(
            document_id=result.document_id,
            chunk_count=result.chunk_count,
            content_hash=result.content_hash,
            message="Questions ingested successfully.",
            processed_count=raw_count,
            deduped_count=len(records),
            top_gaps_found=top_gaps,
            records=records,
        )


@app.post("/diagnosis/gap", response_model=GapAnalysisResponse)
def analyze_gap(request: GapAnalysisRequest) -> GapAnalysisResponse:
    container: AppContainer = app.state.container
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
            top_gaps=[
                {
                    "gap_id": gap.gap_id,
                    "dimension": gap.dimension,
                    "severity": gap.severity,
                    "priority_score": gap.priority_score,
                    "why_it_matters": gap.why_it_matters,
                    "evidence": [
                        {
                            "source_type": item.source_type,
                            "document_id": item.document_id,
                            "chunk_id": item.chunk_id,
                            "text": item.text,
                            "score": item.score,
                            "metadata_summary": item.metadata_summary,
                        }
                        for item in gap.evidence
                    ],
                    "repair_actions": gap.repair_actions,
                }
                for gap in gaps
            ],
        )


@app.get("/diagnosis/current", response_model=GapAnalysisResponse)
def current_gap(user_id: str | None = None, limit: int = 3) -> GapAnalysisResponse:
    container: AppContainer = app.state.container
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
            top_gaps=[
                {
                    "gap_id": gap.gap_id,
                    "dimension": gap.dimension,
                    "severity": gap.severity,
                    "priority_score": gap.priority_score,
                    "why_it_matters": gap.why_it_matters,
                    "evidence": [
                        {
                            "source_type": item.source_type,
                            "document_id": item.document_id,
                            "chunk_id": item.chunk_id,
                            "text": item.text,
                            "score": item.score,
                            "metadata_summary": item.metadata_summary,
                        }
                        for item in gap.evidence
                    ],
                    "repair_actions": gap.repair_actions,
                }
                for gap in gaps
            ],
        )


@app.post("/plan/generate", response_model=PlanResponse)
def generate_plan(request: PlanGenerateRequest) -> PlanResponse:
    container: AppContainer = app.state.container
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


@app.get("/plan/today", response_model=PlanResponse)
def today_plan(user_id: str | None = None) -> PlanResponse:
    container: AppContainer = app.state.container
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


@app.post("/plan/sync_ticktick", response_model=SyncTickTickResponse)
def sync_ticktick(request: SyncTickTickRequest) -> SyncTickTickResponse:
    container: AppContainer = app.state.container
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


@app.post("/agent/turn", response_model=AgentTurnResponse)
async def agent_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    container: AppContainer = app.state.container
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


@app.post("/agent/proactive/tick", response_model=ProactiveTickResponse)
def proactive_tick(request: ProactiveTickRequest) -> ProactiveTickResponse:
    container: AppContainer = app.state.container
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
