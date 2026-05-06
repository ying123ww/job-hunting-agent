from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Sequence

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from interview_agent.storage.models import (
    AbilityScore,
    AnswerRecord,
    Document,
    DocumentChunk,
    GapRecord,
    Plan,
    Project,
    Question,
    TargetJD,
    Task,
    User,
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class InterviewRepository:
    def ensure_user(self, session: Session, user_id: str) -> User:
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            session.add(user)
            session.flush()
        return user

    def deactivate_documents(
        self,
        session: Session,
        *,
        user_id: str,
        source_type: str,
        metadata: dict[str, Any],
        superseded_by: str,
        exclude_document_id: str | None = None,
    ) -> list[str]:
        stmt: Select[tuple[Document]] = select(Document).where(
            Document.user_id == user_id,
            Document.source_type == source_type,
            Document.is_active.is_(True),
        )
        if exclude_document_id:
            stmt = stmt.where(Document.id != exclude_document_id)
        if source_type == "jd":
            company = metadata.get("company")
            role = metadata.get("role")
            if company:
                stmt = stmt.where(func.json_extract(Document.metadata_json, "$.company") == company)
            if role:
                stmt = stmt.where(func.json_extract(Document.metadata_json, "$.role") == role)
        elif source_type != "resume":
            return []

        documents = list(session.scalars(stmt))
        ids: list[str] = []
        for document in documents:
            document.is_active = False
            document.superseded_by = superseded_by
            ids.append(document.id)
        return ids

    def create_document(
        self,
        session: Session,
        *,
        user_id: str,
        source_type: str,
        filename: str | None,
        content_hash: str,
        raw_text: str,
        metadata_json: dict[str, Any],
    ) -> Document:
        document = Document(
            user_id=user_id,
            source_type=source_type,
            filename=filename,
            content_hash=content_hash,
            raw_text=raw_text,
            metadata_json=metadata_json,
        )
        session.add(document)
        session.flush()
        return document

    def create_document_chunk(
        self,
        session: Session,
        *,
        document_id: str,
        user_id: str,
        source_type: str,
        chunk_index: int,
        text: str,
        metadata_json: dict[str, Any],
        vector_collection: str,
        vector_id: str | None,
    ) -> DocumentChunk:
        chunk = DocumentChunk(
            document_id=document_id,
            user_id=user_id,
            source_type=source_type,
            chunk_index=chunk_index,
            text=text,
            metadata_json=metadata_json,
            vector_collection=vector_collection,
            vector_id=vector_id,
        )
        session.add(chunk)
        session.flush()
        return chunk

    def create_target_jd(
        self,
        session: Session,
        *,
        user_id: str,
        document_id: str,
        company: str | None,
        role: str | None,
        raw_text: str,
        structured_requirements: list[dict[str, Any]],
    ) -> TargetJD:
        jd = TargetJD(
            user_id=user_id,
            document_id=document_id,
            company=company,
            role=role,
            raw_text=raw_text,
            structured_requirements=structured_requirements,
        )
        session.add(jd)
        session.flush()
        return jd

    def create_project(
        self,
        session: Session,
        *,
        user_id: str,
        name: str,
        tech_stack: list[str],
        role: str | None,
        metrics: dict[str, Any],
        raw_source_id: str | None,
    ) -> Project:
        project = Project(
            user_id=user_id,
            name=name,
            tech_stack=tech_stack,
            role=role,
            metrics=metrics,
            raw_source_id=raw_source_id,
        )
        session.add(project)
        session.flush()
        return project

    def create_question(
        self,
        session: Session,
        *,
        user_id: str,
        document_id: str,
        source_chunk_id: str,
        text: str,
        source_company: str | None,
        source_role: str | None,
        dimension: str,
        topics: list[str],
        reference_answer: str,
    ) -> Question:
        question = Question(
            user_id=user_id,
            document_id=document_id,
            source_chunk_id=source_chunk_id,
            text=text,
            source_company=source_company,
            source_role=source_role,
            dimension=dimension,
            topics=topics,
            reference_answer=reference_answer,
        )
        session.add(question)
        session.flush()
        return question

    def create_answer_record(
        self,
        session: Session,
        *,
        question_id: str,
        user_id: str,
        user_answer: str,
        mastery_level: str,
        gaps: list[str],
        next_probe: list[str],
    ) -> AnswerRecord:
        record = AnswerRecord(
            question_id=question_id,
            user_id=user_id,
            user_answer=user_answer,
            mastery_level=mastery_level,
            gaps=gaps,
            next_probe=next_probe,
        )
        session.add(record)
        session.flush()
        return record

    def update_question_mastery(
        self,
        session: Session,
        *,
        question_id: str,
        mastery_level: str,
    ) -> None:
        question = session.get(Question, question_id)
        if question is None:
            return
        question.latest_mastery_level = mastery_level
        question.last_answered_at = utcnow()

    def list_questions(self, session: Session, *, user_id: str) -> list[Question]:
        stmt = select(Question).where(Question.user_id == user_id).order_by(desc(Question.last_answered_at))
        return list(session.scalars(stmt))

    def list_answer_records_for_question(
        self,
        session: Session,
        *,
        question_id: str,
    ) -> list[AnswerRecord]:
        stmt = select(AnswerRecord).where(AnswerRecord.question_id == question_id).order_by(desc(AnswerRecord.answered_at))
        return list(session.scalars(stmt))

    def latest_target_jd(self, session: Session, *, user_id: str, jd_id: str | None = None) -> TargetJD | None:
        if jd_id:
            return session.get(TargetJD, jd_id)
        stmt = select(TargetJD).where(TargetJD.user_id == user_id).order_by(desc(TargetJD.created_at)).limit(1)
        return session.scalars(stmt).first()

    def create_gap_record(
        self,
        session: Session,
        *,
        run_id: str,
        user_id: str,
        dimension: str,
        severity: str,
        priority_score: float,
        why_it_matters: str,
        evidence: list[dict[str, Any]],
        repair_actions: list[str],
        source_ids: list[str],
        suggestion: str | None,
    ) -> GapRecord:
        gap = GapRecord(
            run_id=run_id,
            user_id=user_id,
            dimension=dimension,
            severity=severity,
            priority_score=priority_score,
            why_it_matters=why_it_matters,
            evidence=evidence,
            repair_actions=repair_actions,
            source_ids=source_ids,
            suggestion=suggestion,
        )
        session.add(gap)
        session.flush()
        return gap

    def list_latest_gap_records(
        self,
        session: Session,
        *,
        user_id: str,
        limit: int,
    ) -> list[GapRecord]:
        stmt = select(GapRecord).where(GapRecord.user_id == user_id).order_by(desc(GapRecord.created_at)).limit(limit)
        return list(session.scalars(stmt))

    def latest_gap_run(self, session: Session, *, user_id: str, limit: int) -> list[GapRecord]:
        stmt = select(GapRecord.run_id).where(GapRecord.user_id == user_id).order_by(desc(GapRecord.created_at)).limit(1)
        run_id = session.scalars(stmt).first()
        if run_id is None:
            return []
        query = (
            select(GapRecord)
            .where(GapRecord.user_id == user_id, GapRecord.run_id == run_id)
            .order_by(desc(GapRecord.priority_score))
            .limit(limit)
        )
        return list(session.scalars(query))

    def create_plan(
        self,
        session: Session,
        *,
        user_id: str,
        jd_id: str | None,
        start_date: date,
        end_date: date,
        summary: str,
    ) -> Plan:
        plan = Plan(
            user_id=user_id,
            jd_id=jd_id,
            start_date=start_date,
            end_date=end_date,
            summary=summary,
        )
        session.add(plan)
        session.flush()
        return plan

    def create_task(
        self,
        session: Session,
        *,
        user_id: str,
        plan_id: str,
        title: str,
        dimension: str,
        priority: int,
        due_at: datetime,
        duration_min: int,
        reason: str,
    ) -> Task:
        task = Task(
            user_id=user_id,
            plan_id=plan_id,
            title=title,
            dimension=dimension,
            priority=priority,
            due_at=due_at,
            duration_min=duration_min,
            reason=reason,
        )
        session.add(task)
        session.flush()
        return task

    def list_tasks_for_day(self, session: Session, *, user_id: str, day: date) -> list[Task]:
        stmt = (
            select(Task)
            .where(
                Task.user_id == user_id,
                func.date(Task.due_at) == day.isoformat(),
            )
            .order_by(Task.due_at)
        )
        return list(session.scalars(stmt))

    def latest_plan(self, session: Session, *, user_id: str) -> Plan | None:
        stmt = select(Plan).where(Plan.user_id == user_id).order_by(desc(Plan.created_at)).limit(1)
        return session.scalars(stmt).first()

    def tasks_for_plan(self, session: Session, *, plan_id: str) -> list[Task]:
        stmt = select(Task).where(Task.plan_id == plan_id).order_by(Task.due_at)
        return list(session.scalars(stmt))

    def active_chunk_lookup(
        self,
        session: Session,
        *,
        user_id: str,
        source_types: Sequence[str] | None = None,
    ) -> dict[str, DocumentChunk]:
        stmt = (
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.user_id == user_id, Document.is_active.is_(True))
        )
        if source_types:
            stmt = stmt.where(DocumentChunk.source_type.in_(source_types))
        rows = session.execute(stmt).all()
        return {chunk.id: chunk for chunk, _ in rows}

    def get_document_chunk(self, session: Session, *, chunk_id: str) -> DocumentChunk | None:
        return session.get(DocumentChunk, chunk_id)

    def list_documents(self, session: Session, *, user_id: str, source_type: str) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.user_id == user_id, Document.source_type == source_type)
            .order_by(desc(Document.created_at))
        )
        return list(session.scalars(stmt))

    def list_chunks_for_documents(self, session: Session, *, document_ids: Sequence[str]) -> list[DocumentChunk]:
        if not document_ids:
            return []
        stmt = select(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids))
        return list(session.scalars(stmt))

    def upsert_ability_score(
        self,
        session: Session,
        *,
        user_id: str,
        dimension: str,
        score: float,
        confidence: float,
    ) -> None:
        current = session.get(AbilityScore, (user_id, dimension))
        if current is None:
            current = AbilityScore(
                user_id=user_id,
                dimension=dimension,
                score=score,
                confidence=confidence,
            )
            session.add(current)
        else:
            current.score = score
            current.confidence = confidence
            current.updated_at = utcnow()
