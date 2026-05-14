from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any, Literal

from sqlalchemy.orm import Session

from interview_agent.diagnosis.service import GapAnalysisService
from interview_agent.ingestion.service import QuestionCandidate, QuestionIngestionService
from interview_agent.retrieval.service import EvidenceItem, RetrievalService
from interview_agent.storage.models import MockAnswer, MockQuestion, MockSession, Question
from interview_agent.storage.repositories import InterviewRepository


MockMode = Literal["weakness_global", "weakness_dimension", "jd"]
SourceKind = Literal["original", "variant", "generated"]

QUESTION_COUNT_DEFAULT = 20
ORIGINAL_TARGET = 12
VARIANT_TARGET = 8


@dataclass(slots=True)
class MockQuestionView:
    mock_question_id: str
    prompt: str
    reference_answer: str
    dimension: str
    topics: list[str]
    source_kind: str
    source_question_id: str | None
    evidence: list[dict[str, Any]]
    position: int
    answer: "MockAnswerView | None" = None


@dataclass(slots=True)
class MockAnswerView:
    mock_answer_id: str
    mock_question_id: str
    user_answer: str
    mastery_level: str
    gaps: list[str]
    next_probe: list[str]
    accuracy_score: int | None
    structure_score: int | None
    depth_score: int | None
    score_summary: str | None
    answered_at: datetime


@dataclass(slots=True)
class MockSessionView:
    session_id: str
    mode: str
    jd_id: str | None
    target_dimension: str | None
    status: str
    question_count: int
    source_mix: dict[str, Any]
    summary: str
    created_at: datetime
    completed_at: datetime | None
    questions: list[MockQuestionView]


@dataclass(slots=True)
class SubmittedMockAnswer:
    mock_question_id: str
    user_answer: str


class MockInterviewService:
    def __init__(
        self,
        *,
        repository: InterviewRepository,
        retrieval: RetrievalService,
        diagnosis: GapAnalysisService,
        question_ingestion: QuestionIngestionService,
    ) -> None:
        self.repository = repository
        self.retrieval = retrieval
        self.diagnosis = diagnosis
        self.question_ingestion = question_ingestion

    def create_session(
        self,
        session: Session,
        *,
        user_id: str,
        mode: MockMode,
        jd_id: str | None,
        target_dimension: str | None,
        question_count: int = QUESTION_COUNT_DEFAULT,
    ) -> MockSessionView:
        question_count = max(1, min(question_count, QUESTION_COUNT_DEFAULT))
        jd = self.repository.resolve_target_jd(session, user_id=user_id, requested_jd_id=jd_id) if mode == "jd" else None
        resolved_jd_id = jd.id if jd is not None else None
        dimensions = self._target_dimensions(
            session,
            user_id=user_id,
            mode=mode,
            jd_id=resolved_jd_id,
            target_dimension=target_dimension,
            jd_requirements=jd.structured_requirements if jd is not None else [],
        )
        pool = self._rank_question_pool(
            session,
            user_id=user_id,
            dimensions=dimensions,
            strict_dimension=mode == "weakness_dimension",
        )
        specs = self._build_question_specs(
            session,
            user_id=user_id,
            mode=mode,
            dimensions=dimensions,
            questions=pool,
            jd_id=resolved_jd_id,
            jd_requirements=jd.structured_requirements if jd is not None else [],
            question_count=question_count,
        )
        source_mix = dict(Counter(spec["source_kind"] for spec in specs))
        mock_session = self.repository.create_mock_session(
            session,
            user_id=user_id,
            mode=mode,
            jd_id=resolved_jd_id,
            target_dimension=target_dimension,
            question_count=question_count,
            source_mix=source_mix,
        )
        for index, spec in enumerate(specs, start=1):
            self.repository.create_mock_question(
                session,
                session_id=mock_session.id,
                question_id=spec.get("question_id"),
                prompt=spec["prompt"],
                reference_answer=spec["reference_answer"],
                dimension=spec["dimension"],
                topics=list(spec.get("topics") or []),
                source_kind=spec["source_kind"],
                source_question_id=spec.get("source_question_id"),
                evidence=list(spec.get("evidence") or []),
                position=index,
            )
        self.repository.update_mock_session_state(session, session_id=mock_session.id, status="in_progress")
        return self.get_session(session, user_id=user_id, session_id=mock_session.id)

    def get_session(self, session: Session, *, user_id: str, session_id: str) -> MockSessionView:
        item = self.repository.get_mock_session(session, session_id=session_id)
        if item is None or item.user_id != user_id:
            raise ValueError(f"Mock session {session_id!r} was not found.")
        return self._session_view(session, item)

    def list_sessions(self, session: Session, *, user_id: str, limit: int = 20) -> list[MockSessionView]:
        return [self._session_view(session, item, include_questions=False) for item in self.repository.list_mock_sessions(session, user_id=user_id, limit=limit)]

    def submit_answers(
        self,
        session: Session,
        *,
        user_id: str,
        session_id: str,
        answers: list[SubmittedMockAnswer],
    ) -> MockSessionView:
        mock_session = self.repository.get_mock_session(session, session_id=session_id)
        if mock_session is None or mock_session.user_id != user_id:
            raise ValueError(f"Mock session {session_id!r} was not found.")
        question_lookup = {item.id: item for item in self.repository.list_mock_questions(session, session_id=session_id)}
        for submitted in answers:
            question = question_lookup.get(submitted.mock_question_id)
            if question is None:
                raise ValueError(f"Mock question {submitted.mock_question_id!r} was not found in this session.")
            assessment = self.question_ingestion._evaluate_candidate(  # Reuse the existing question assessment pipeline.
                QuestionCandidate(
                    question=question.prompt,
                    answer=submitted.user_answer,
                    source_company=None,
                    source_role=None,
                    dimension=question.dimension,
                    topics=list(question.topics),
                    reference_answer=question.reference_answer,
                    block_text=self._block_text(question.prompt, submitted.user_answer),
                )
            )
            self.repository.upsert_mock_answer(
                session,
                mock_question_id=question.id,
                user_id=user_id,
                user_answer=submitted.user_answer,
                mastery_level=assessment.mastery_level,
                gaps=assessment.gaps,
                next_probe=assessment.next_probe,
                accuracy_score=assessment.accuracy_score,
                structure_score=assessment.structure_score,
                depth_score=assessment.depth_score,
                score_summary=assessment.score_summary,
            )
            if question.source_kind == "original" and question.source_question_id:
                self.repository.create_answer_record(
                    session,
                    question_id=question.source_question_id,
                    user_id=user_id,
                    user_answer=submitted.user_answer,
                    mastery_level=assessment.mastery_level,
                    gaps=assessment.gaps,
                    next_probe=assessment.next_probe,
                )
                self.repository.update_question_mastery(
                    session,
                    question_id=question.source_question_id,
                    mastery_level=assessment.mastery_level,
                )
        return self.get_session(session, user_id=user_id, session_id=session_id)

    def complete_session(self, session: Session, *, user_id: str, session_id: str) -> MockSessionView:
        item = self.repository.get_mock_session(session, session_id=session_id)
        if item is None or item.user_id != user_id:
            raise ValueError(f"Mock session {session_id!r} was not found.")
        questions = self.repository.list_mock_questions(session, session_id=session_id)
        answers = self.repository.list_mock_answers_for_session(session, session_id=session_id)
        summary = self._summary(questions=questions, answers=answers)
        self.repository.update_mock_session_state(
            session,
            session_id=session_id,
            status="completed",
            summary=summary,
            completed_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.diagnosis.analyze(session, user_id=user_id, jd_id=item.jd_id, limit=3, persist=True)
        return self.get_session(session, user_id=user_id, session_id=session_id)

    def _target_dimensions(
        self,
        session: Session,
        *,
        user_id: str,
        mode: MockMode,
        jd_id: str | None,
        target_dimension: str | None,
        jd_requirements: list[dict[str, Any]],
    ) -> list[str]:
        if mode == "weakness_dimension" and target_dimension:
            return [target_dimension]
        if mode == "jd":
            weighted = sorted(
                ((str(item.get("dimension") or "backend_basic"), float(item.get("weight", 0.45))) for item in jd_requirements),
                key=lambda pair: pair[1],
                reverse=True,
            )
            dims = self._dedupe([dimension for dimension, _ in weighted])
            if dims:
                return dims
        _, gaps = self.diagnosis.current(session, user_id=user_id, jd_id=jd_id, limit=5)
        dims = [gap.dimension for gap in gaps]
        if not dims:
            dims = [item.dimension for item in self.repository.list_questions(session, user_id=user_id) if item.dimension]
        return self._dedupe(dims) or [target_dimension or "backend_basic"]

    def _rank_question_pool(
        self,
        session: Session,
        *,
        user_id: str,
        dimensions: list[str],
        strict_dimension: bool = False,
    ) -> list[Question]:
        wanted = set(dimensions)
        questions = self.repository.list_questions(session, user_id=user_id, active_only=True)
        matching = [item for item in questions if not wanted or item.dimension in wanted]
        fallback = [] if strict_dimension else [item for item in questions if item not in matching]
        ranked = [*matching, *fallback]
        ranked.sort(key=lambda item: self._question_priority(item, wanted), reverse=True)
        return ranked

    def _question_priority(self, question: Question, wanted: set[str]) -> tuple[int, int, int]:
        mastery_score = 2 if question.latest_mastery_level == "需要加强" else 1 if question.latest_mastery_level in {"部分掌握", "未评估"} else 0
        dimension_score = 1 if question.dimension in wanted else 0
        recency_score = 1 if question.last_answered_at is not None else 0
        return mastery_score, dimension_score, recency_score

    def _build_question_specs(
        self,
        session: Session,
        *,
        user_id: str,
        mode: MockMode,
        dimensions: list[str],
        questions: list[Question],
        jd_id: str | None,
        jd_requirements: list[dict[str, Any]],
        question_count: int,
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        seen_prompts: set[str] = set()
        original_target = ORIGINAL_TARGET if mode != "jd" else min(ORIGINAL_TARGET, question_count)
        variant_target = VARIANT_TARGET if mode != "jd" else min(VARIANT_TARGET, max(question_count - original_target, 0))
        for question in questions:
            if len([item for item in specs if item["source_kind"] == "original"]) >= original_target:
                break
            self._append_spec(specs, seen_prompts, self._original_spec(question))
        for question in questions:
            if len([item for item in specs if item["source_kind"] == "variant"]) >= variant_target:
                break
            self._append_spec(specs, seen_prompts, self._variant_spec(question))
        requirement_index = 0
        attempts = 0
        max_attempts = max(question_count * 3, 12)
        while len(specs) < question_count and attempts < max_attempts:
            dimension = dimensions[(len(specs) + attempts) % len(dimensions)] if dimensions else "backend_basic"
            requirement = jd_requirements[requirement_index % len(jd_requirements)] if jd_requirements else {}
            requirement_index += 1
            attempts += 1
            evidence = self._evidence_for_dimension(session, user_id=user_id, dimension=dimension, jd_id=jd_id, requirement=requirement)
            self._append_spec(
                specs,
                seen_prompts,
                self._generated_spec(
                    dimension=dimension,
                    requirement=requirement,
                    evidence=evidence,
                    index=len(specs) + attempts,
                ),
            )
        while len(specs) < question_count:
            dimension = dimensions[len(specs) % len(dimensions)] if dimensions else "backend_basic"
            self._append_spec(
                specs,
                seen_prompts,
                self._fallback_generated_spec(dimension=dimension, index=len(specs)),
            )
        return specs[:question_count]

    def _append_spec(self, specs: list[dict[str, Any]], seen_prompts: set[str], spec: dict[str, Any]) -> None:
        normalized = self._normalize(spec["prompt"])
        if not normalized or normalized in seen_prompts:
            return
        specs.append(spec)
        seen_prompts.add(normalized)

    def _original_spec(self, question: Question) -> dict[str, Any]:
        return {
            "question_id": question.id,
            "prompt": question.text,
            "reference_answer": question.reference_answer,
            "dimension": question.dimension,
            "topics": list(question.topics),
            "source_kind": "original",
            "source_question_id": question.id,
            "evidence": [{"source_type": "question", "question_id": question.id, "text": question.text}],
        }

    def _variant_spec(self, question: Question) -> dict[str, Any]:
        topic_text = "、".join(question.topics[:3]) or question.dimension
        return {
            "question_id": None,
            "prompt": f"变种题：如果面试官围绕 `{topic_text}` 继续追问：{question.text}，你会如何从原理、边界和项目经验三个角度回答？",
            "reference_answer": question.reference_answer,
            "dimension": question.dimension,
            "topics": list(question.topics),
            "source_kind": "variant",
            "source_question_id": question.id,
            "evidence": [{"source_type": "question", "question_id": question.id, "text": question.text}],
        }

    def _generated_spec(self, *, dimension: str, requirement: dict[str, Any], evidence: list[EvidenceItem], index: int) -> dict[str, Any]:
        requirement_text = str(requirement.get("text") or requirement.get("requirement") or "").strip()
        topics = [str(topic).strip() for topic in requirement.get("topics", []) if str(topic).strip()]
        anchor = requirement_text or ("、".join(topics) if topics else dimension)
        prompt = f"岗位匹配题 {index + 1}：请结合你的项目经历说明 `{anchor}`，并解释关键方案、取舍和可量化结果。"
        return {
            "question_id": None,
            "prompt": prompt,
            "reference_answer": f"回答应覆盖 `{anchor}` 的核心概念、项目证据、技术取舍、失败场景和结果指标。",
            "dimension": dimension,
            "topics": topics or [dimension],
            "source_kind": "generated",
            "source_question_id": None,
            "evidence": [self._evidence_payload(item) for item in evidence[:3]],
        }

    def _fallback_generated_spec(self, *, dimension: str, index: int) -> dict[str, Any]:
        anchor = f"{dimension} 核心能力点 {index + 1}"
        return {
            "question_id": None,
            "prompt": f"补齐题 {index + 1}：请系统说明 `{anchor}`，并补充一个你在项目中验证过的例子。",
            "reference_answer": f"回答应覆盖 `{anchor}` 的概念、实践路径、边界条件和可复盘结果。",
            "dimension": dimension,
            "topics": [dimension],
            "source_kind": "generated",
            "source_question_id": None,
            "evidence": [],
        }

    def _evidence_for_dimension(self, session: Session, *, user_id: str, dimension: str, jd_id: str | None, requirement: dict[str, Any]) -> list[EvidenceItem]:
        query = str(requirement.get("text") or requirement.get("requirement") or dimension)
        return self.retrieval.build_evidence_bundle(
            session,
            user_id=user_id,
            query_text=query,
            source_types=["resume", "jd", "question"],
            dimension=dimension,
            jd_id=jd_id,
            limit=3,
        )

    def _session_view(self, session: Session, item: MockSession, *, include_questions: bool = True) -> MockSessionView:
        questions: list[MockQuestionView] = []
        if include_questions:
            answers = {answer.mock_question_id: self._answer_view(answer) for answer in self.repository.list_mock_answers_for_session(session, session_id=item.id)}
            questions = [self._question_view(question, answers.get(question.id)) for question in self.repository.list_mock_questions(session, session_id=item.id)]
        return MockSessionView(
            session_id=item.id,
            mode=item.mode,
            jd_id=item.jd_id,
            target_dimension=item.target_dimension,
            status=item.status,
            question_count=item.question_count,
            source_mix=dict(item.source_mix or {}),
            summary=item.summary,
            created_at=item.created_at,
            completed_at=item.completed_at,
            questions=questions,
        )

    def _question_view(self, item: MockQuestion, answer: MockAnswerView | None) -> MockQuestionView:
        return MockQuestionView(
            mock_question_id=item.id,
            prompt=item.prompt,
            reference_answer=item.reference_answer,
            dimension=item.dimension,
            topics=list(item.topics),
            source_kind=item.source_kind,
            source_question_id=item.source_question_id,
            evidence=list(item.evidence or []),
            position=item.position,
            answer=answer,
        )

    def _answer_view(self, item: MockAnswer) -> MockAnswerView:
        return MockAnswerView(
            mock_answer_id=item.id,
            mock_question_id=item.mock_question_id,
            user_answer=item.user_answer,
            mastery_level=item.mastery_level,
            gaps=list(item.gaps),
            next_probe=list(item.next_probe),
            accuracy_score=item.accuracy_score,
            structure_score=item.structure_score,
            depth_score=item.depth_score,
            score_summary=item.score_summary,
            answered_at=item.answered_at,
        )

    def _summary(self, *, questions: list[MockQuestion], answers: list[MockAnswer]) -> str:
        answered_count = len(answers)
        avg_accuracy = self._avg([item.accuracy_score for item in answers])
        avg_structure = self._avg([item.structure_score for item in answers])
        avg_depth = self._avg([item.depth_score for item in answers])
        weak_dimensions = Counter(question.dimension for question in questions if question.id in {answer.mock_question_id for answer in answers if answer.mastery_level != "熟练掌握"})
        top_weak = ", ".join(dimension for dimension, _ in weak_dimensions.most_common(3)) or "none"
        return (
            f"完成 {answered_count}/{len(questions)} 题。"
            f"平均分：准确性 {avg_accuracy:.1f}，结构 {avg_structure:.1f}，深度 {avg_depth:.1f}。"
            f"优先复盘维度：{top_weak}。"
        )

    def _avg(self, values: list[int | None]) -> float:
        present = [value for value in values if value is not None]
        if not present:
            return 0.0
        return sum(present) / len(present)

    def _evidence_payload(self, item: EvidenceItem) -> dict[str, Any]:
        return {
            "source_type": item.source_type,
            "document_id": item.document_id,
            "chunk_id": item.chunk_id,
            "text": item.text,
            "score": item.score,
            "metadata_summary": item.metadata_summary,
        }

    def _block_text(self, question: str, answer: str) -> str:
        return f"{question}\n我的答案：{answer}"

    def _dedupe(self, items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            normalized = str(item).strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    def _normalize(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().lower()
