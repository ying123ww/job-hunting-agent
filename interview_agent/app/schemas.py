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


class QuestionIngestRequest(BaseIngestRequest):
    source_company: str | None = None
    source_role: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    chunk_count: int
    content_hash: str
    message: str


class QuestionRecordResponse(BaseModel):
    question_id: str
    question: str
    dimension: str
    topics: list[str]
    mastery_level: str
    gaps: list[str]
    next_probe: list[str]


class QuestionIngestResponse(IngestResponse):
    processed_count: int
    deduped_count: int
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
