from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BaseIngestRequest(BaseModel):
    user_id: str | None = None
    text: str | None = None
    content_base64: str | None = None
    filename: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content(self) -> "BaseIngestRequest":
        if not self.text and not self.content_base64:
            raise ValueError("Either text or content_base64 must be provided.")
        return self


class ResumeIngestRequest(BaseIngestRequest):
    pass


class JDIngestRequest(BaseIngestRequest):
    company: str | None = None
    role: str | None = None
    url: str | None = None
    job_description: str | None = None
    job_requirements: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_text_from_sections(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("text") or data.get("content_base64"):
            return data
        description = str(data.get("job_description") or "").strip()
        requirements = str(data.get("job_requirements") or "").strip()
        sections: list[str] = []
        if description:
            sections.append(f"职位描述\n{description}")
        if requirements:
            sections.append(f"职位要求\n{requirements}")
        if not sections:
            return data
        return {**data, "text": "\n\n".join(sections)}


class QuestionIngestRequest(BaseIngestRequest):
    source_company: str | None = None
    source_role: str | None = None
    evaluate_answers: bool = True


class QuestionEvaluateRequest(BaseModel):
    user_id: str | None = None
    document_id: str


class IngestResponse(BaseModel):
    document_id: str
    chunk_count: int
    content_hash: str
    message: str


class ResumeSourceUpdateRequest(BaseModel):
    user_id: str | None = None
    source: str


class ResumeSourceResponse(BaseModel):
    source: str
    last_saved_at: datetime | None = None
    last_compiled_at: datetime | None = None
    last_compile_status: str
    last_compile_error_summary: str | None = None
    last_resume_document_id: str | None = None
    compiler_available: bool
    pdf_exists: bool


class ResumeCompileResponse(BaseModel):
    last_compiled_at: datetime
    last_compile_status: str
    last_compile_error_summary: str | None = None
    compiler_available: bool
    pdf_exists: bool
    log_excerpt: str


class QuestionRecordResponse(BaseModel):
    question_id: str
    question: str
    user_answer: str
    reference_answer: str
    dimension: str
    topics: list[str]
    mastery_level: str
    gaps: list[str]
    next_probe: list[str]
    accuracy_score: int | None = None
    structure_score: int | None = None
    depth_score: int | None = None
    score_summary: str | None = None
    evaluation_status: str = "completed"


class QuestionIngestResponse(IngestResponse):
    processed_count: int
    deduped_count: int
    skipped_count: int = 0
    inactive_count: int = 0
    fallback_used: bool = False
    pipeline_version: str = "question_ingestion_v2"
    top_gaps_found: list[str]
    records: list[QuestionRecordResponse]


class QuestionEvaluateResponse(BaseModel):
    document_id: str
    evaluated_count: int
    top_gaps_found: list[str]
    records: list[QuestionRecordResponse]


class EvidenceResponse(BaseModel):
    source_type: str
    document_id: str
    chunk_id: str
    text: str
    score: float
    metadata_summary: dict[str, Any] = Field(default_factory=dict)


class GapResponse(BaseModel):
    gap_id: str
    dimension: str
    severity: str
    priority_score: float
    why_it_matters: str
    evidence: list[EvidenceResponse]
    repair_actions: list[str]


class GapAnalysisRequest(BaseModel):
    user_id: str | None = None
    jd_id: str | None = None
    limit: int = Field(default=3, ge=1, le=10)


class GapAnalysisResponse(BaseModel):
    jd_id: str | None = None
    overall_risk: str
    generated_at: datetime
    top_gaps: list[GapResponse]


class PlanGenerateRequest(BaseModel):
    user_id: str | None = None
    jd_id: str | None = None
    gap_limit: int = Field(default=3, ge=1, le=10)
    target_date: date | None = None


class TaskResponse(BaseModel):
    task_id: str
    title: str
    dimension: str
    priority: int
    due_at: datetime
    duration_min: int
    status: str
    reason: str


class PlanResponse(BaseModel):
    plan_id: str
    jd_id: str | None = None
    summary: str
    tasks: list[TaskResponse]


class DocumentSummaryResponse(BaseModel):
    document_id: str
    source_type: str
    filename: str | None = None
    content_hash: str
    is_active: bool
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentDetailResponse(DocumentSummaryResponse):
    raw_text_preview: str


class QuestionBankDetailResponse(DocumentSummaryResponse):
    question_count: int = 0
    evaluation_status: str = "pending"
    overall_mastery: str | None = None
    summary: str | None = None
    top_gaps_found: list[str] = Field(default_factory=list)
    mastery_counts: dict[str, int] = Field(default_factory=dict)
    records: list[QuestionRecordResponse]


class WorkspaceOverviewResponse(BaseModel):
    active_document_counts: dict[str, int]
    latest_overall_risk: str | None = None
    top_gaps: list[GapResponse]
    today_plan: PlanResponse
    ticktick_sync_mode: Literal["dry_run", "live"]


class JDRecordResponse(BaseModel):
    jd_id: str
    document_id: str | None = None
    company: str | None = None
    role: str | None = None
    url: str | None = None
    job_description: str | None = None
    job_requirements: str | None = None
    created_at: datetime
    is_current: bool


class CurrentJDUpdateRequest(BaseModel):
    user_id: str | None = None
    jd_id: str


class CurrentJDUpdateResponse(BaseModel):
    current_jd_id: str | None = None


class ResumeTailorDraftRequest(BaseModel):
    user_id: str | None = None
    jd_id: str | None = None


class ResumeTailorDraftResponse(BaseModel):
    jd_id: str | None = None
    summary: str
    highlighted_keywords: list[str]
    suggestions: list[str]


class SyncTickTickRequest(BaseModel):
    user_id: str | None = None
    plan_id: str | None = None


class SyncTickTickResponse(BaseModel):
    synced: int
    mode: Literal["dry_run", "live"]
    tasks: list[TaskResponse]


class AgentTurnRequest(BaseModel):
    user_id: str | None = None
    jd_id: str | None = None
    message: str = Field(min_length=1)


class AgentTurnResponse(BaseModel):
    turn_id: str
    intent: str
    reply: str
    current_jd_id: str | None = None
    generated_plan_id: str | None = None
    evidence: list[EvidenceResponse]
    lifecycle: list[str]
    memory_now: dict[str, str] = Field(default_factory=dict)


class ProactiveTickRequest(BaseModel):
    user_id: str | None = None
    jd_id: str | None = None
    force: bool = False


class ProactiveTickResponse(BaseModel):
    tick_id: str
    action: str
    message: str
    generated_plan_id: str | None = None
    drift_entered: bool = False


class HealthResponse(BaseModel):
    status: str
    app_name: str
