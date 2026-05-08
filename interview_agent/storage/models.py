from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    weak_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    learning_preference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latest_overall_risk: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("doc"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("chunk"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    vector_collection: Mapped[str] = mapped_column(String)
    vector_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TargetJD(Base):
    __tablename__ = "target_jds"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("jd"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    structured_requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("proj"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    tech_stack: Mapped[list[str]] = mapped_column(JSON, default=list)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_source_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AbilityScore(Base):
    __tablename__ = "ability_scores"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    dimension: Mapped[str] = mapped_column(String, primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("q"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    source_chunk_id: Mapped[str | None] = mapped_column(ForeignKey("document_chunks.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    source_company: Mapped[str | None] = mapped_column(String, nullable=True)
    source_role: Mapped[str | None] = mapped_column(String, nullable=True)
    dimension: Mapped[str] = mapped_column(String, index=True)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    reference_answer: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    question_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    source_scope: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_mastery_level: Mapped[str] = mapped_column(String, default="未评估")
    last_answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnswerRecord(Base):
    __tablename__ = "answer_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("ans"))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    user_answer: Mapped[str] = mapped_column(Text)
    mastery_level: Mapped[str] = mapped_column(String)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_probe: Mapped[list[str]] = mapped_column(JSON, default=list)
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GapRecord(Base):
    __tablename__ = "gap_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("gap"))
    run_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    dimension: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String)
    priority_score: Mapped[float] = mapped_column(Float)
    why_it_matters: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    repair_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("mem"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    memory_type: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    reinforcement: Mapped[int] = mapped_column(Integer, default=1)
    emotional_weight: Mapped[int] = mapped_column(Integer, default=0)
    extra_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    happened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active", index=True)
    vector_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("plan"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    jd_id: Mapped[str | None] = mapped_column(ForeignKey("target_jds.id"), nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="active")
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: make_id("task"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    dimension: Mapped[str] = mapped_column(String, index=True)
    priority: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    duration_min: Mapped[int] = mapped_column(Integer, default=25)
    ticktick_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
