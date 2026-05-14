from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import re
from typing import Any, Sequence

from sqlalchemy import Select, desc, func, select, text
from sqlalchemy.orm import Session

from interview_agent.storage.models import (
    AbilityScore,
    AnswerRecord,
    Document,
    DocumentChunk,
    GapRecord,
    MemoryItem,
    MockAnswer,
    MockQuestion,
    MockSession,
    Plan,
    Project,
    Question,
    TargetJD,
    Task,
    User,
    UserProfile,
)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


@dataclass(slots=True)
class LexicalMatch:
    item_id: str
    item_type: str
    source_type: str
    document_id: str
    chunk_id: str
    text: str
    dimension: str | None
    question_id: str | None
    topics_text: str
    source_scope: str | None
    rank: float


def build_question_searchable_text(question: Question) -> str:
    parts = [
        question.text,
        question.reference_answer,
        " ".join(topic for topic in question.topics if topic),
        question.source_company or "",
        question.source_role or "",
    ]
    return "\n".join(part.strip() for part in parts if part and part.strip())


def build_chunk_searchable_text(chunk: DocumentChunk) -> str:
    metadata = chunk.metadata_json or {}
    parts = [
        chunk.text,
        str(metadata.get("topics_text", "")),
        str(metadata.get("source_company", "")),
        str(metadata.get("source_role", "")),
        str(metadata.get("dimension", "")),
        str(metadata.get("company", "")),
        str(metadata.get("role", "")),
        str(metadata.get("url", "")),
    ]
    return "\n".join(part.strip() for part in parts if part and part.strip())


class InterviewRepository:
    def ensure_user(self, session: Session, user_id: str) -> User:
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            session.add(user)
            session.flush()
        return user

    def get_user_profile(self, session: Session, *, user_id: str) -> UserProfile | None:
        return session.get(UserProfile, user_id)

    def upsert_user_profile(
        self,
        session: Session,
        *,
        user_id: str,
        target_roles: Sequence[str] | None = None,
        target_companies: Sequence[str] | None = None,
        current_jd_id: str | None = None,
        weak_points: Sequence[str] | None = None,
        learning_preference: dict[str, Any] | None = None,
        latest_overall_risk: str | None = None,
    ) -> UserProfile:
        self.ensure_user(session, user_id)
        profile = session.get(UserProfile, user_id)
        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                learning_preference=dict(learning_preference or {}),
            )
            session.add(profile)
            session.flush()
        if target_roles:
            profile.target_roles = self._merge_unique(profile.target_roles, target_roles)
        if target_companies:
            profile.target_companies = self._merge_unique(profile.target_companies, target_companies)
        if current_jd_id is not None:
            profile.current_jd_id = current_jd_id
        if weak_points is not None:
            profile.weak_points = [item for item in weak_points if item]
        if learning_preference:
            profile.learning_preference = {**profile.learning_preference, **learning_preference}
        if latest_overall_risk is not None:
            profile.latest_overall_risk = latest_overall_risk
        profile.updated_at = utcnow()
        return profile

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
            url = metadata.get("url")
            if url:
                stmt = stmt.where(func.json_extract(Document.metadata_json, "$.url") == url)
            else:
                company = metadata.get("company")
                role = metadata.get("role")
                if company:
                    stmt = stmt.where(func.json_extract(Document.metadata_json, "$.company") == company)
                if role:
                    stmt = stmt.where(func.json_extract(Document.metadata_json, "$.role") == role)
        elif source_type == "question":
            source_scope = metadata.get("source_scope")
            if not source_scope:
                return []
            stmt = stmt.where(func.json_extract(Document.metadata_json, "$.source_scope") == source_scope)
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

    def update_document_metadata(self, session: Session, *, document_id: str, metadata_json: dict[str, Any]) -> Document | None:
        document = session.get(Document, document_id)
        if document is None:
            return None
        document.metadata_json = metadata_json
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
        url: str | None,
        job_description: str | None,
        job_requirements: str | None,
        raw_text: str,
        structured_requirements: list[dict[str, Any]],
    ) -> TargetJD:
        jd = TargetJD(
            user_id=user_id,
            document_id=document_id,
            company=company,
            role=role,
            url=url,
            job_description=job_description,
            job_requirements=job_requirements,
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

    def delete_projects_for_source_documents(self, session: Session, *, document_ids: Sequence[str]) -> None:
        if not document_ids:
            return
        session.query(Project).filter(Project.raw_source_id.in_(document_ids)).delete(
            synchronize_session=False
        )

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
        normalized_text: str,
        question_fingerprint: str,
        source_scope: str | None,
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
            normalized_text=normalized_text,
            question_fingerprint=question_fingerprint,
            source_scope=source_scope,
        )
        session.add(question)
        session.flush()
        return question

    def deactivate_question(self, session: Session, *, question_id: str, superseded_by: str | None = None) -> Question | None:
        question = session.get(Question, question_id)
        if question is None:
            return None
        question.is_active = False
        question.superseded_by = superseded_by
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

    def list_questions(self, session: Session, *, user_id: str, active_only: bool = True) -> list[Question]:
        stmt = select(Question).where(Question.user_id == user_id)
        if active_only:
            stmt = stmt.where(Question.is_active.is_(True))
        stmt = stmt.order_by(desc(Question.last_answered_at))
        return list(session.scalars(stmt))

    def list_questions_for_scope(
        self,
        session: Session,
        *,
        user_id: str,
        source_scope: str,
        active_only: bool = True,
    ) -> list[Question]:
        stmt = select(Question).where(
            Question.user_id == user_id,
            Question.source_scope == source_scope,
        )
        if active_only:
            stmt = stmt.where(Question.is_active.is_(True))
        stmt = stmt.order_by(desc(Question.last_answered_at))
        return list(session.scalars(stmt))

    def list_questions_for_document(
        self,
        session: Session,
        *,
        user_id: str,
        document_id: str,
        active_only: bool = True,
    ) -> list[Question]:
        stmt = select(Question).where(
            Question.user_id == user_id,
            Question.document_id == document_id,
        )
        if active_only:
            stmt = stmt.where(Question.is_active.is_(True))
        stmt = stmt.order_by(Question.source_chunk_id)
        return list(session.scalars(stmt))

    def list_answer_records_for_question(
        self,
        session: Session,
        *,
        question_id: str,
    ) -> list[AnswerRecord]:
        stmt = select(AnswerRecord).where(AnswerRecord.question_id == question_id).order_by(desc(AnswerRecord.answered_at))
        return list(session.scalars(stmt))

    def create_mock_session(
        self,
        session: Session,
        *,
        user_id: str,
        mode: str,
        jd_id: str | None,
        target_dimension: str | None,
        question_count: int,
        source_mix: dict[str, Any],
    ) -> MockSession:
        self.ensure_user(session, user_id)
        item = MockSession(
            user_id=user_id,
            mode=mode,
            jd_id=jd_id,
            target_dimension=target_dimension,
            status="draft",
            question_count=question_count,
            source_mix=source_mix,
            summary="",
        )
        session.add(item)
        session.flush()
        return item

    def create_mock_question(
        self,
        session: Session,
        *,
        session_id: str,
        question_id: str | None,
        prompt: str,
        reference_answer: str,
        dimension: str,
        topics: list[str],
        source_kind: str,
        source_question_id: str | None,
        evidence: list[dict[str, Any]],
        position: int,
    ) -> MockQuestion:
        item = MockQuestion(
            session_id=session_id,
            question_id=question_id,
            prompt=prompt,
            reference_answer=reference_answer,
            dimension=dimension,
            topics=topics,
            source_kind=source_kind,
            source_question_id=source_question_id,
            evidence=evidence,
            position=position,
        )
        session.add(item)
        session.flush()
        return item

    def get_mock_session(self, session: Session, *, session_id: str) -> MockSession | None:
        return session.get(MockSession, session_id)

    def list_mock_sessions(self, session: Session, *, user_id: str, limit: int = 20) -> list[MockSession]:
        stmt = (
            select(MockSession)
            .where(MockSession.user_id == user_id)
            .order_by(desc(MockSession.created_at))
            .limit(limit)
        )
        return list(session.scalars(stmt))

    def list_mock_questions(self, session: Session, *, session_id: str) -> list[MockQuestion]:
        stmt = select(MockQuestion).where(MockQuestion.session_id == session_id).order_by(MockQuestion.position)
        return list(session.scalars(stmt))

    def get_mock_question(self, session: Session, *, mock_question_id: str) -> MockQuestion | None:
        return session.get(MockQuestion, mock_question_id)

    def upsert_mock_answer(
        self,
        session: Session,
        *,
        mock_question_id: str,
        user_id: str,
        user_answer: str,
        mastery_level: str,
        gaps: list[str],
        next_probe: list[str],
        accuracy_score: int | None,
        structure_score: int | None,
        depth_score: int | None,
        score_summary: str | None,
    ) -> MockAnswer:
        existing = session.scalars(
            select(MockAnswer).where(MockAnswer.mock_question_id == mock_question_id, MockAnswer.user_id == user_id)
        ).first()
        if existing is None:
            existing = MockAnswer(
                mock_question_id=mock_question_id,
                user_id=user_id,
                user_answer=user_answer,
                mastery_level=mastery_level,
                gaps=gaps,
                next_probe=next_probe,
                accuracy_score=accuracy_score,
                structure_score=structure_score,
                depth_score=depth_score,
                score_summary=score_summary,
            )
            session.add(existing)
        else:
            existing.user_answer = user_answer
            existing.mastery_level = mastery_level
            existing.gaps = gaps
            existing.next_probe = next_probe
            existing.accuracy_score = accuracy_score
            existing.structure_score = structure_score
            existing.depth_score = depth_score
            existing.score_summary = score_summary
            existing.answered_at = utcnow()
        session.flush()
        return existing

    def list_mock_answers_for_session(self, session: Session, *, session_id: str) -> list[MockAnswer]:
        stmt = (
            select(MockAnswer)
            .join(MockQuestion, MockQuestion.id == MockAnswer.mock_question_id)
            .where(MockQuestion.session_id == session_id)
            .order_by(MockQuestion.position)
        )
        return list(session.scalars(stmt))

    def update_mock_session_state(
        self,
        session: Session,
        *,
        session_id: str,
        status: str | None = None,
        summary: str | None = None,
        completed_at: datetime | None = None,
        source_mix: dict[str, Any] | None = None,
    ) -> MockSession | None:
        item = session.get(MockSession, session_id)
        if item is None:
            return None
        if status is not None:
            item.status = status
        if summary is not None:
            item.summary = summary
        if completed_at is not None:
            item.completed_at = completed_at
        if source_mix is not None:
            item.source_mix = source_mix
        session.flush()
        return item

    def get_target_jd(self, session: Session, *, jd_id: str) -> TargetJD | None:
        return session.get(TargetJD, jd_id)

    def latest_target_jd(self, session: Session, *, user_id: str, jd_id: str | None = None) -> TargetJD | None:
        if jd_id:
            return self.get_target_jd(session, jd_id=jd_id)
        stmt = select(TargetJD).where(TargetJD.user_id == user_id).order_by(desc(TargetJD.created_at)).limit(1)
        return session.scalars(stmt).first()

    def resolve_target_jd(self, session: Session, *, user_id: str, requested_jd_id: str | None) -> TargetJD | None:
        if requested_jd_id:
            return self.get_target_jd(session, jd_id=requested_jd_id)
        profile = self.get_user_profile(session, user_id=user_id)
        if profile is not None and profile.current_jd_id:
            current = self.get_target_jd(session, jd_id=profile.current_jd_id)
            if current is not None:
                return current
        return self.latest_target_jd(session, user_id=user_id)

    def list_target_jds(self, session: Session, *, user_id: str) -> list[TargetJD]:
        stmt = select(TargetJD).where(TargetJD.user_id == user_id).order_by(desc(TargetJD.created_at))
        return list(session.scalars(stmt))

    def create_gap_record(
        self,
        session: Session,
        *,
        run_id: str,
        user_id: str,
        jd_id: str | None,
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
            jd_id=jd_id,
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

    def latest_gap_run(self, session: Session, *, user_id: str, jd_id: str | None = None, limit: int) -> list[GapRecord]:
        stmt = select(GapRecord.run_id).where(GapRecord.user_id == user_id)
        if jd_id is not None:
            stmt = stmt.where(GapRecord.jd_id == jd_id)
        stmt = stmt.order_by(desc(GapRecord.created_at)).limit(1)
        run_id = session.scalars(stmt).first()
        if run_id is None:
            return []
        query = select(GapRecord).where(GapRecord.user_id == user_id, GapRecord.run_id == run_id)
        if jd_id is not None:
            query = query.where(GapRecord.jd_id == jd_id)
        query = query.order_by(desc(GapRecord.priority_score)).limit(limit)
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

    def update_task_sync_state(
        self,
        session: Session,
        *,
        task_id: str,
        ticktick_id: str | None = None,
        status: str | None = None,
    ) -> Task | None:
        task = session.get(Task, task_id)
        if task is None:
            return None
        if ticktick_id is not None:
            task.ticktick_id = ticktick_id
        if status is not None:
            task.status = status
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

    def latest_plan(self, session: Session, *, user_id: str, jd_id: str | None = None) -> Plan | None:
        stmt = select(Plan).where(Plan.user_id == user_id)
        if jd_id is not None:
            stmt = stmt.where(Plan.jd_id == jd_id)
        stmt = stmt.order_by(desc(Plan.created_at)).limit(1)
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

    def list_documents(
        self,
        session: Session,
        *,
        user_id: str,
        source_type: str | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> list[Document]:
        stmt = select(Document).where(Document.user_id == user_id)
        if source_type is not None:
            stmt = stmt.where(Document.source_type == source_type)
        if active_only:
            stmt = stmt.where(Document.is_active.is_(True))
        stmt = stmt.order_by(desc(Document.created_at))
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def get_document(self, session: Session, *, document_id: str) -> Document | None:
        return session.get(Document, document_id)

    def count_active_documents_by_source(self, session: Session, *, user_id: str) -> dict[str, int]:
        rows = session.execute(
            select(Document.source_type, func.count(Document.id))
            .where(Document.user_id == user_id, Document.is_active.is_(True))
            .group_by(Document.source_type)
        ).all()
        counts = {"resume": 0, "jd": 0, "question": 0}
        for source_type, count in rows:
            counts[str(source_type)] = int(count)
        return counts

    def list_chunks_for_documents(self, session: Session, *, document_ids: Sequence[str]) -> list[DocumentChunk]:
        if not document_ids:
            return []
        stmt = select(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids))
        return list(session.scalars(stmt))

    def delete_document_chunks(self, session: Session, *, document_ids: Sequence[str]) -> None:
        if not document_ids:
            return
        session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(document_ids)).delete(
            synchronize_session=False
        )

    def delete_documents(self, session: Session, *, document_ids: Sequence[str]) -> None:
        if not document_ids:
            return
        session.query(Document).filter(Document.id.in_(document_ids)).delete(synchronize_session=False)

    def list_active_document_chunks(
        self,
        session: Session,
        *,
        user_id: str,
        source_types: Sequence[str] | None = None,
    ) -> list[DocumentChunk]:
        stmt = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.user_id == user_id, Document.is_active.is_(True))
            .order_by(DocumentChunk.chunk_index)
        )
        if source_types:
            stmt = stmt.where(DocumentChunk.source_type.in_(source_types))
        return list(session.scalars(stmt))

    def get_question(self, session: Session, *, question_id: str) -> Question | None:
        return session.get(Question, question_id)

    def update_retrieval_fts(
        self,
        session: Session,
        *,
        item_id: str,
        item_type: str,
        searchable_text: str,
        is_active: bool,
        user_id: str,
        source_scope: str | None,
        source_type: str,
        dimension: str | None,
    ) -> None:
        session.execute(text("DELETE FROM retrieval_fts WHERE item_id = :item_id"), {"item_id": item_id})
        session.execute(
            text(
                "INSERT INTO retrieval_fts (item_id, item_type, searchable_text, is_active, user_id, source_scope, source_type, dimension) "
                "VALUES (:item_id, :item_type, :searchable_text, :is_active, :user_id, :source_scope, :source_type, :dimension)"
            ),
            {
                "item_id": item_id,
                "item_type": item_type,
                "searchable_text": searchable_text,
                "is_active": 1 if is_active else 0,
                "user_id": user_id,
                "source_scope": source_scope or "",
                "source_type": source_type,
                "dimension": dimension or "",
            },
        )

    def delete_retrieval_fts(self, session: Session, *, item_id: str) -> None:
        session.execute(text("DELETE FROM retrieval_fts WHERE item_id = :item_id"), {"item_id": item_id})

    def lexical_search(
        self,
        session: Session,
        *,
        user_id: str,
        query_text: str,
        source_types: Sequence[str] | None,
        limit: int,
    ) -> list[LexicalMatch]:
        sanitized_query = self._sanitize_fts_query(query_text)
        if not sanitized_query:
            return []
        params: dict[str, Any] = {
            "query_text": sanitized_query,
            "user_id": user_id,
            "limit": limit,
        }
        filters = [
            "retrieval_fts MATCH :query_text",
            "user_id = :user_id",
            "is_active = 1",
        ]
        if source_types:
            placeholders: list[str] = []
            for index, source_type in enumerate(source_types):
                key = f"source_type_{index}"
                params[key] = source_type
                placeholders.append(f":{key}")
            filters.append(f"source_type IN ({', '.join(placeholders)})")

        rows = session.execute(
            text(
                "SELECT item_id, item_type, source_type, source_scope, dimension, bm25(retrieval_fts) AS rank "
                "FROM retrieval_fts "
                f"WHERE {' AND '.join(filters)} "
                "ORDER BY rank LIMIT :limit"
            ),
            params,
        ).mappings().all()
        if not rows:
            return []

        question_ids = [row["item_id"] for row in rows if row["item_type"] == "question"]
        chunk_ids = [row["item_id"] for row in rows if row["item_type"] == "chunk"]
        questions = (
            {item.id: item for item in session.scalars(select(Question).where(Question.id.in_(question_ids)))}
            if question_ids
            else {}
        )
        chunks = (
            {item.id: item for item in session.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))}
            if chunk_ids
            else {}
        )

        matches: list[LexicalMatch] = []
        for row in rows:
            if row["item_type"] == "question":
                question = questions.get(row["item_id"])
                if question is None:
                    continue
                matches.append(
                    LexicalMatch(
                        item_id=question.id,
                        item_type="question",
                        source_type="question",
                        document_id=question.document_id or "",
                        chunk_id=question.source_chunk_id or "",
                        text=question.text,
                        dimension=question.dimension,
                        question_id=question.id,
                        topics_text=",".join(question.topics),
                        source_scope=question.source_scope,
                        rank=float(row["rank"] or 0.0),
                    )
                )
                continue

            chunk = chunks.get(row["item_id"])
            if chunk is None:
                continue
            metadata = chunk.metadata_json or {}
            matches.append(
                LexicalMatch(
                    item_id=chunk.id,
                    item_type="chunk",
                    source_type=chunk.source_type,
                    document_id=chunk.document_id,
                    chunk_id=chunk.id,
                    text=chunk.text,
                    dimension=str(metadata.get("dimension") or "") or None,
                    question_id=str(metadata.get("question_id") or "") or None,
                    topics_text=str(metadata.get("topics_text") or ""),
                    source_scope=str(metadata.get("source_scope") or "") or None,
                    rank=float(row["rank"] or 0.0),
                )
                )
        return matches

    def _sanitize_fts_query(self, query_text: str) -> str:
        tokens = _FTS_TOKEN_RE.findall(query_text.lower())
        return " OR ".join(tokens[:8]).strip()

    def rebuild_retrieval_fts(self, session: Session, *, user_id: str | None = None) -> None:
        if user_id is None:
            session.execute(text("DELETE FROM retrieval_fts"))
        else:
            session.execute(text("DELETE FROM retrieval_fts WHERE user_id = :user_id"), {"user_id": user_id})

        question_stmt = select(Question).where(Question.is_active.is_(True))
        chunk_stmt = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.is_active.is_(True))
        )
        if user_id is not None:
            question_stmt = question_stmt.where(Question.user_id == user_id)
            chunk_stmt = chunk_stmt.where(DocumentChunk.user_id == user_id)

        for question in session.scalars(question_stmt):
            self.update_retrieval_fts(
                session,
                item_id=question.id,
                item_type="question",
                searchable_text=build_question_searchable_text(question),
                is_active=True,
                user_id=question.user_id,
                source_scope=question.source_scope,
                source_type="question",
                dimension=question.dimension,
            )
        for chunk in session.scalars(chunk_stmt):
            metadata = chunk.metadata_json or {}
            self.update_retrieval_fts(
                session,
                item_id=chunk.id,
                item_type="chunk",
                searchable_text=build_chunk_searchable_text(chunk),
                is_active=True,
                user_id=chunk.user_id,
                source_scope=str(metadata.get("source_scope") or "") or None,
                source_type=chunk.source_type,
                dimension=str(metadata.get("dimension") or "") or None,
            )

    def find_memory_item_by_hash(
        self,
        session: Session,
        *,
        user_id: str,
        memory_type: str,
        content_hash: str,
    ) -> MemoryItem | None:
        stmt = (
            select(MemoryItem)
            .where(
                MemoryItem.user_id == user_id,
                MemoryItem.memory_type == memory_type,
                MemoryItem.content_hash == content_hash,
                MemoryItem.status == "active",
            )
            .limit(1)
        )
        return session.scalars(stmt).first()

    def create_memory_item(
        self,
        session: Session,
        *,
        user_id: str,
        memory_type: str,
        summary: str,
        content_hash: str,
        emotional_weight: int,
        extra_json: dict[str, Any],
        source_ref: str | None,
        happened_at: datetime | None,
        vector_id: str | None,
    ) -> MemoryItem:
        item = MemoryItem(
            user_id=user_id,
            memory_type=memory_type,
            summary=summary,
            content_hash=content_hash,
            emotional_weight=emotional_weight,
            extra_json=extra_json,
            source_ref=source_ref,
            happened_at=happened_at,
            vector_id=vector_id,
        )
        session.add(item)
        session.flush()
        return item

    def reinforce_memory_item(
        self,
        session: Session,
        *,
        item_id: str,
        extra_json: dict[str, Any] | None = None,
        happened_at: datetime | None = None,
    ) -> MemoryItem | None:
        item = session.get(MemoryItem, item_id)
        if item is None:
            return None
        item.reinforcement += 1
        if extra_json:
            item.extra_json = {**item.extra_json, **extra_json}
        if happened_at is not None:
            item.happened_at = happened_at
        item.updated_at = utcnow()
        return item

    def list_memory_items_by_ids(self, session: Session, *, ids: Sequence[str]) -> list[MemoryItem]:
        if not ids:
            return []
        stmt = select(MemoryItem).where(MemoryItem.id.in_(ids), MemoryItem.status == "active")
        items = list(session.scalars(stmt))
        order = {item_id: index for index, item_id in enumerate(ids)}
        items.sort(key=lambda item: order.get(item.id, 10**9))
        return items

    def list_memory_items(
        self,
        session: Session,
        *,
        user_id: str,
        memory_types: Sequence[str] | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        stmt = (
            select(MemoryItem)
            .where(MemoryItem.user_id == user_id, MemoryItem.status == "active")
            .order_by(desc(MemoryItem.updated_at))
            .limit(limit)
        )
        if memory_types:
            stmt = stmt.where(MemoryItem.memory_type.in_(memory_types))
        return list(session.scalars(stmt))

    def list_ability_scores(self, session: Session, *, user_id: str) -> list[AbilityScore]:
        stmt = select(AbilityScore).where(AbilityScore.user_id == user_id).order_by(desc(AbilityScore.updated_at))
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

    def _merge_unique(self, current: Sequence[str], incoming: Sequence[str]) -> list[str]:
        merged = list(current)
        seen = {item for item in merged if item}
        for item in incoming:
            normalized = str(item).strip()
            if not normalized or normalized in seen:
                continue
            merged.append(normalized)
            seen.add(normalized)
        return merged
