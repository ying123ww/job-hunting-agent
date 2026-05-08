from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response

from interview_agent.agent.runtime import AgentTurnRequest as RuntimeAgentTurnRequest
from interview_agent.actions.ticktick import SyncMode
from interview_agent.app.config import get_settings
from interview_agent.app.schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
    CurrentJDUpdateRequest,
    CurrentJDUpdateResponse,
    DocumentDetailResponse,
    DocumentSummaryResponse,
    GapAnalysisRequest,
    GapAnalysisResponse,
    HealthResponse,
    IngestResponse,
    JDRecordResponse,
    JDIngestRequest,
    PlanGenerateRequest,
    PlanResponse,
    ProactiveTickRequest,
    ProactiveTickResponse,
    QuestionIngestRequest,
    QuestionIngestResponse,
    ResumeCompileResponse,
    ResumeIngestRequest,
    ResumeSourceResponse,
    ResumeSourceUpdateRequest,
    ResumeTailorDraftRequest,
    ResumeTailorDraftResponse,
    SyncTickTickRequest,
    SyncTickTickResponse,
    TaskResponse,
    WorkspaceOverviewResponse,
)
from interview_agent.core.container import AppContainer
from interview_agent.ingestion.parser import compose_jd_source_text, split_jd_sections


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


def _resolve_jd_sections(request: JDIngestRequest) -> tuple[str | None, str | None]:
    if request.job_description or request.job_requirements:
        return request.job_description, request.job_requirements
    if request.text:
        return split_jd_sections(request.text)
    return None, None


def _resolve_target_jd(session, container: AppContainer, *, user_id: str, requested_jd_id: str | None):
    if requested_jd_id:
        jd = container.repository.get_target_jd(session, jd_id=requested_jd_id)
        if jd is None or jd.user_id != user_id:
            raise HTTPException(status_code=404, detail=f"JD {requested_jd_id!r} was not found.")
        return jd
    return container.repository.resolve_target_jd(session, user_id=user_id, requested_jd_id=None)


def _resolve_jd_id(session, container: AppContainer, *, user_id: str, requested_jd_id: str | None) -> str | None:
    jd = _resolve_target_jd(session, container, user_id=user_id, requested_jd_id=requested_jd_id)
    return jd.id if jd is not None else None


def _jd_record_response(jd, *, current_jd_id: str | None) -> JDRecordResponse:
    return JDRecordResponse(
        jd_id=jd.id,
        document_id=jd.document_id,
        company=jd.company,
        role=jd.role,
        url=jd.url,
        job_description=jd.job_description,
        job_requirements=jd.job_requirements,
        created_at=jd.created_at,
        is_current=jd.id == current_jd_id,
    )


def _tailor_keywords(jd) -> list[str]:
    keywords: list[str] = []
    for requirement in jd.structured_requirements[:6]:
        for topic in requirement.get("topics", []):
            normalized = str(topic).strip()
            if normalized and normalized != "General" and normalized not in keywords:
                keywords.append(normalized)
        dimension = str(requirement.get("dimension") or "").strip()
        if dimension and dimension not in keywords:
            keywords.append(dimension)
    return keywords[:6]


def _resume_tailor_draft(container: AppContainer, session, *, user_id: str, jd) -> ResumeTailorDraftResponse:
    if jd is None:
        raise HTTPException(status_code=400, detail="Create or select a JD before generating a resume tailor draft.")

    requirements = jd.structured_requirements[:5]
    keywords = _tailor_keywords(jd)
    query_text = "简历 项目经历 bullet " + " ".join(
        str(item.get("text") or "").strip() for item in requirements if str(item.get("text") or "").strip()
    )
    evidence = container.retrieval.build_evidence_bundle(
        session,
        user_id=user_id,
        query_text=query_text.strip() or "简历 项目经历 bullet",
        jd_id=jd.id,
        limit=6,
    )
    resume_text = container.resume_workspace.get_source_snapshot().source.lower()
    resume_hits = [item for item in evidence if item.source_type == "resume"]
    matched_requirements = 0
    suggestions: list[str] = []
    for requirement in requirements:
        requirement_text = str(requirement.get("text") or "").strip()
        if not requirement_text:
            continue
        topics = [
            str(topic).strip()
            for topic in requirement.get("topics", [])
            if str(topic).strip() and str(topic).strip() != "General"
        ]
        anchors = topics[:2] or [requirement_text[:24]]
        matched = any(topic.lower() in resume_text for topic in topics) if topics else requirement_text.lower() in resume_text
        if matched:
            matched_requirements += 1
            suggestions.append(
                f"把与 `{anchors[0]}` 相关的项目 bullet 前移，并补规模、结果或 trade-off，直接对齐 `{requirement_text}`。"
            )
        else:
            suggestions.append(
                f"新增或改写一条项目 bullet，显式体现 `{anchors[0]}`，避免只写通用职责，目标对齐 `{requirement_text}`。"
            )
    if keywords:
        suggestions.append(f"在 Summary 或 Skills 里显式补上关键词：{', '.join(keywords[:4])}。")
    summary = (
        f"当前 JD 重点覆盖 {', '.join(keywords[:4]) or '核心后端能力'}；"
        f" 当前简历在 {matched_requirements}/{max(len(requirements), 1)} 条核心要求上已有明显对应。"
    )
    if resume_hits:
        summary += " 已从已保存简历内容里检索到相关证据，可优先强化这些命中经历。"
    return ResumeTailorDraftResponse(
        jd_id=jd.id,
        summary=summary,
        highlighted_keywords=keywords,
        suggestions=suggestions[:6],
    )


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


def _resume_source_response(snapshot) -> ResumeSourceResponse:
    return ResumeSourceResponse(
        source=snapshot.source,
        last_saved_at=snapshot.last_saved_at,
        last_compiled_at=snapshot.last_compiled_at,
        last_compile_status=snapshot.last_compile_status,
        last_compile_error_summary=snapshot.last_compile_error_summary,
        last_resume_document_id=snapshot.last_resume_document_id,
        compiler_available=snapshot.compiler_available,
        pdf_exists=snapshot.pdf_exists,
    )


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
            "resume_source": "/resume/source",
            "resume_compile": "/resume/compile",
            "resume_pdf": "/resume/pdf",
            "resume_compile_log": "/resume/compile-log",
            "ingest_resume": "/ingest/resume",
            "ingest_jd": "/ingest/jd",
            "jds": "/jds",
            "jds_current": "/jds/current",
            "ingest_questions": "/ingest/questions",
            "diagnosis_gap": "/diagnosis/gap",
            "diagnosis_current": "/diagnosis/current",
            "plan_generate": "/plan/generate",
            "plan_today": "/plan/today",
            "plan_sync_ticktick": "/plan/sync_ticktick",
            "resume_tailor_draft": "/resume/tailor-draft",
            "agent_turn": "/agent/turn",
            "agent_proactive_tick": "/agent/proactive/tick",
            "workspace_overview": "/workspace/overview",
            "documents": "/documents",
        },
    }


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/resume/source", response_model=ResumeSourceResponse)
async def resume_source(http_request: Request) -> ResumeSourceResponse:
    container = _container(http_request)
    return _resume_source_response(container.resume_workspace.get_source_snapshot())


@router.put("/resume/source", response_model=ResumeSourceResponse)
async def save_resume_source(
    http_request: Request,
    request: ResumeSourceUpdateRequest,
) -> ResumeSourceResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        result = container.resume_workspace.save_source(
            session,
            user_id=user_id,
            source=request.source,
        )
        return _resume_source_response(result)


@router.post("/resume/compile", response_model=ResumeCompileResponse)
async def compile_resume(http_request: Request) -> ResumeCompileResponse:
    container = _container(http_request)
    result = container.resume_workspace.compile_source()
    return ResumeCompileResponse(
        last_compiled_at=result.last_compiled_at,
        last_compile_status=result.last_compile_status,
        last_compile_error_summary=result.last_compile_error_summary,
        compiler_available=result.compiler_available,
        pdf_exists=result.pdf_exists,
        log_excerpt=result.log_excerpt,
    )


@router.get("/resume/pdf")
async def resume_pdf(http_request: Request):
    container = _container(http_request)
    container.resume_workspace.ensure_workspace_files()
    pdf_path = container.settings.resume_pdf_path
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Resume PDF has not been compiled yet.")
    return FileResponse(pdf_path, media_type="application/pdf")


@router.get("/resume/compile-log")
async def resume_compile_log(http_request: Request) -> PlainTextResponse:
    container = _container(http_request)
    container.resume_workspace.ensure_workspace_files()
    return PlainTextResponse(container.settings.resume_compile_log_path.read_text(encoding="utf-8"))


@router.post("/ingest/resume", response_model=IngestResponse)
async def ingest_resume(http_request: Request, request: ResumeIngestRequest) -> IngestResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        result = container.resume_workspace.save_imported_source(
            session,
            user_id=user_id,
            text=request.text,
            content_base64=request.content_base64,
            filename=request.filename,
        )
        return IngestResponse(
            document_id=result.last_resume_document_id or "",
            chunk_count=result.chunk_count,
            content_hash=result.content_hash,
            message="Resume source saved successfully.",
        )


@router.post("/ingest/jd", response_model=IngestResponse)
async def ingest_jd(http_request: Request, request: JDIngestRequest) -> IngestResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    job_description, job_requirements = _resolve_jd_sections(request)
    resolved_text = request.text or compose_jd_source_text(
        job_description=job_description,
        job_requirements=job_requirements,
    )
    metadata = {
        **request.metadata,
        "company": request.company,
        "role": request.role,
        "url": request.url,
        "job_description": job_description,
        "job_requirements": job_requirements,
    }
    with container.db.session_scope() as session:
        result = container.document_ingestion.ingest_document(
            session,
            user_id=user_id,
            source_type="jd",
            text=resolved_text,
            content_base64=request.content_base64,
            filename=request.filename,
            metadata=metadata,
        )
        if not job_description and not job_requirements:
            job_description, job_requirements = split_jd_sections(result.raw_text)
            metadata = {
                **metadata,
                "job_description": job_description,
                "job_requirements": job_requirements,
            }
            container.repository.update_document_metadata(
                session,
                document_id=result.document_id,
                metadata_json=metadata,
            )
        jd = container.document_ingestion.persist_jd_side_effects(
            session,
            user_id=user_id,
            document_id=result.document_id,
            text=result.raw_text,
            company=request.company,
            role=request.role,
            url=request.url,
            job_description=job_description,
            job_requirements=job_requirements,
        )
        container.repository.upsert_user_profile(
            session,
            user_id=user_id,
            current_jd_id=jd.id,
        )
        return IngestResponse(
            document_id=result.document_id,
            chunk_count=result.chunk_count,
            content_hash=result.content_hash,
            message="JD ingested successfully.",
        )


@router.get("/jds", response_model=list[JDRecordResponse])
async def list_jds(http_request: Request, user_id: str | None = None) -> list[JDRecordResponse]:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        current = container.repository.resolve_target_jd(session, user_id=resolved_user_id, requested_jd_id=None)
        records = container.repository.list_target_jds(session, user_id=resolved_user_id)
        return [_jd_record_response(item, current_jd_id=current.id if current is not None else None) for item in records]


@router.put("/jds/current", response_model=CurrentJDUpdateResponse)
async def set_current_jd(http_request: Request, request: CurrentJDUpdateRequest) -> CurrentJDUpdateResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        jd = _resolve_target_jd(session, container, user_id=user_id, requested_jd_id=request.jd_id)
        if jd is None:
            raise HTTPException(status_code=404, detail=f"JD {request.jd_id!r} was not found.")
        container.repository.upsert_user_profile(
            session,
            user_id=user_id,
            current_jd_id=jd.id,
        )
        return CurrentJDUpdateResponse(current_jd_id=jd.id)


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
        resolved_jd_id = _resolve_jd_id(session, container, user_id=user_id, requested_jd_id=request.jd_id)
        overall_risk, gaps = container.diagnosis.analyze(
            session,
            user_id=user_id,
            jd_id=resolved_jd_id,
            limit=request.limit,
            persist=True,
        )
        return GapAnalysisResponse(
            jd_id=resolved_jd_id,
            overall_risk=overall_risk,
            generated_at=_utcnow(),
            top_gaps=[_gap_response(gap) for gap in gaps],
        )


@router.get("/diagnosis/current", response_model=GapAnalysisResponse)
async def current_gap(
    http_request: Request,
    user_id: str | None = None,
    jd_id: str | None = None,
    limit: int = 3,
) -> GapAnalysisResponse:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        resolved_jd_id = _resolve_jd_id(session, container, user_id=resolved_user_id, requested_jd_id=jd_id)
        overall_risk, gaps = container.diagnosis.current(
            session,
            user_id=resolved_user_id,
            jd_id=resolved_jd_id,
            limit=limit,
        )
        return GapAnalysisResponse(
            jd_id=resolved_jd_id,
            overall_risk=overall_risk,
            generated_at=_utcnow(),
            top_gaps=[_gap_response(gap) for gap in gaps],
        )


@router.post("/plan/generate", response_model=PlanResponse)
async def generate_plan(http_request: Request, request: PlanGenerateRequest) -> PlanResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        resolved_jd_id = _resolve_jd_id(session, container, user_id=user_id, requested_jd_id=request.jd_id)
        plan = container.planning.generate(
            session,
            user_id=user_id,
            jd_id=resolved_jd_id,
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
async def today_plan(http_request: Request, user_id: str | None = None, jd_id: str | None = None) -> PlanResponse:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        resolved_jd_id = _resolve_jd_id(session, container, user_id=resolved_user_id, requested_jd_id=jd_id)
        plan = container.planning.today(session, user_id=resolved_user_id, jd_id=resolved_jd_id, day=None)
        if plan is None:
            return PlanResponse(plan_id="", jd_id=resolved_jd_id, summary="No plan for today.", tasks=[])
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
async def workspace_overview(
    http_request: Request,
    user_id: str | None = None,
    jd_id: str | None = None,
) -> WorkspaceOverviewResponse:
    container = _container(http_request)
    resolved_user_id = _user_id(container, user_id)
    with container.db.session_scope() as session:
        resolved_jd_id = _resolve_jd_id(session, container, user_id=resolved_user_id, requested_jd_id=jd_id)
        counts = container.repository.count_active_documents_by_source(
            session,
            user_id=resolved_user_id,
        )
        overall_risk, gaps = container.diagnosis.current(
            session,
            user_id=resolved_user_id,
            jd_id=resolved_jd_id,
            limit=3,
        )
        today_plan_result = container.planning.today(
            session,
            user_id=resolved_user_id,
            jd_id=resolved_jd_id,
            day=None,
        )
        if today_plan_result is None:
            today_plan = PlanResponse(
                plan_id="",
                jd_id=resolved_jd_id,
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
            latest_overall_risk=overall_risk if gaps else None,
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
        resolved_jd_id = _resolve_jd_id(session, container, user_id=user_id, requested_jd_id=request.jd_id)
        result = await container.agent_runtime.run_turn(
            session,
            RuntimeAgentTurnRequest(
                user_id=user_id,
                message=request.message,
                jd_id=resolved_jd_id,
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
        resolved_jd_id = _resolve_jd_id(session, container, user_id=user_id, requested_jd_id=request.jd_id)
        result = container.proactive_service.tick(
            session,
            user_id=user_id,
            current_jd_id=resolved_jd_id,
            force=request.force,
        )
        return ProactiveTickResponse(
            tick_id=result.tick_id,
            action=result.action,
            message=result.message,
            generated_plan_id=result.generated_plan_id,
            drift_entered=result.drift_entered,
        )


@router.post("/resume/tailor-draft", response_model=ResumeTailorDraftResponse)
async def resume_tailor_draft(
    http_request: Request,
    request: ResumeTailorDraftRequest,
) -> ResumeTailorDraftResponse:
    container = _container(http_request)
    user_id = _user_id(container, request.user_id)
    with container.db.session_scope() as session:
        jd = _resolve_target_jd(session, container, user_id=user_id, requested_jd_id=request.jd_id)
        return _resume_tailor_draft(container, session, user_id=user_id, jd=jd)


app = create_app()
