from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from interview_agent.retrieval.service import EvidenceItem, RetrievalService
from interview_agent.storage.models import Question, make_id
from interview_agent.storage.repositories import InterviewRepository
from interview_agent.storage.vector_store import ChromaVectorStore


MASTERY_TO_SEVERITY = {
    "熟练掌握": 0.15,
    "部分掌握": 0.55,
    "需要加强": 0.9,
    "未评估": 0.7,
}

SEVERITY_LABELS = (
    (0.8, "high"),
    (0.55, "medium"),
    (0.0, "low"),
)


def compute_priority_score(
    *,
    jd_weight: float,
    weakness_severity: float,
    evidence_confidence: float,
    repeated_failure_factor: float,
    recent_improvement: float,
) -> float:
    return round(
        jd_weight
        * weakness_severity
        * evidence_confidence
        * repeated_failure_factor
        * (1 - recent_improvement),
        4,
    )


@dataclass(slots=True)
class DiagnosedGap:
    gap_id: str
    dimension: str
    severity: str
    priority_score: float
    why_it_matters: str
    evidence: list[EvidenceItem]
    repair_actions: list[str]


class GapAnalysisService:
    def __init__(
        self,
        *,
        repository: InterviewRepository,
        retrieval: RetrievalService,
        vector_store: ChromaVectorStore,
    ) -> None:
        self.repository = repository
        self.retrieval = retrieval
        self.vector_store = vector_store

    def analyze(
        self,
        session: Session,
        *,
        user_id: str,
        jd_id: str | None,
        limit: int,
        persist: bool = True,
    ) -> tuple[str, list[DiagnosedGap]]:
        jd = self.repository.latest_target_jd(session, user_id=user_id, jd_id=jd_id)
        questions = self.repository.list_questions(session, user_id=user_id)
        if not questions:
            return "low", []

        jd_weights = self._jd_weight_map(jd.structured_requirements if jd else [])
        dimension_buckets: dict[str, list[Question]] = defaultdict(list)
        for question in questions:
            dimension_buckets[question.dimension].append(question)

        run_id = make_id("gaprun")
        gaps: list[DiagnosedGap] = []
        for dimension, items in dimension_buckets.items():
            weakness_severity = max(MASTERY_TO_SEVERITY.get(item.latest_mastery_level, 0.7) for item in items)
            jd_weight = jd_weights.get(dimension, 0.45)
            repeated_failure_factor = min(1.5, 1.0 + 0.15 * max(len(items) - 1, 0))
            evidence_confidence = 0.9 if len(items) > 1 else 0.7
            recent_improvement = 0.2 if any(item.latest_mastery_level == "熟练掌握" for item in items) else 0.0
            priority_score = compute_priority_score(
                jd_weight=jd_weight,
                weakness_severity=weakness_severity,
                evidence_confidence=evidence_confidence,
                repeated_failure_factor=repeated_failure_factor,
                recent_improvement=recent_improvement,
            )
            severity = self._severity_label(priority_score)
            query_text = items[0].text
            evidence = self.retrieval.build_evidence_bundle(
                session,
                user_id=user_id,
                query_text=query_text,
                source_types=["resume", "jd", "question"],
                dimension=dimension,
                limit=4,
            )
            repair_actions = self._repair_actions(dimension=dimension, questions=items)
            why_it_matters = self._why_it_matters(dimension=dimension, jd_weight=jd_weight, questions=items)
            diagnosed = DiagnosedGap(
                gap_id=make_id("gap"),
                dimension=dimension,
                severity=severity,
                priority_score=priority_score,
                why_it_matters=why_it_matters,
                evidence=evidence,
                repair_actions=repair_actions,
            )
            gaps.append(diagnosed)
            if persist:
                record = self.repository.create_gap_record(
                    session,
                    run_id=run_id,
                    user_id=user_id,
                    dimension=dimension,
                    severity=severity,
                    priority_score=priority_score,
                    why_it_matters=why_it_matters,
                    evidence=[
                        {
                            "source_type": item.source_type,
                            "document_id": item.document_id,
                            "chunk_id": item.chunk_id,
                            "text": item.text,
                            "score": item.score,
                            "metadata_summary": item.metadata_summary,
                        }
                        for item in evidence
                    ],
                    repair_actions=repair_actions,
                    source_ids=[item.document_id for item in evidence if item.document_id],
                    suggestion=repair_actions[0] if repair_actions else None,
                )
                gap_summary = f"{dimension}: {why_it_matters}\n修复动作：{'；'.join(repair_actions)}"
                self.vector_store.upsert(
                    collection_name="gap_memory",
                    ids=[record.id],
                    texts=[gap_summary],
                    metadatas=[
                        {
                            "user_id": user_id,
                            "source_type": "gap_record",
                            "document_id": evidence[0].document_id if evidence else "",
                            "chunk_id": record.id,
                            "question_id": "",
                            "dimension": dimension,
                            "topics_text": "",
                            "is_active": True,
                        }
                    ],
                )
        gaps.sort(key=lambda item: item.priority_score, reverse=True)
        top_gaps = gaps[:limit]
        overall_risk = self._overall_risk(top_gaps)
        self._update_ability_scores(session, user_id=user_id, gaps=top_gaps)
        self.repository.upsert_user_profile(
            session,
            user_id=user_id,
            weak_points=[gap.dimension for gap in top_gaps],
            latest_overall_risk=overall_risk,
        )
        return overall_risk, top_gaps

    def current(self, session: Session, *, user_id: str, limit: int) -> tuple[str, list[DiagnosedGap]]:
        records = self.repository.latest_gap_run(session, user_id=user_id, limit=limit)
        gaps = [
            DiagnosedGap(
                gap_id=record.id,
                dimension=record.dimension,
                severity=record.severity,
                priority_score=record.priority_score,
                why_it_matters=record.why_it_matters,
                evidence=[
                    EvidenceItem(
                        source_type=item["source_type"],
                        document_id=item["document_id"],
                        chunk_id=item["chunk_id"],
                        text=item["text"],
                        score=item["score"],
                        metadata_summary=item.get("metadata_summary", {}),
                    )
                    for item in record.evidence
                ],
                repair_actions=record.repair_actions,
            )
            for record in records
        ]
        return self._overall_risk(gaps), gaps

    def _jd_weight_map(self, requirements: list[dict[str, Any]]) -> dict[str, float]:
        mapping: dict[str, float] = defaultdict(lambda: 0.45)
        for item in requirements:
            dimension = str(item.get("dimension", "backend_basic"))
            weight = float(item.get("weight", 0.45))
            mapping[dimension] = max(mapping[dimension], weight)
        return mapping

    def _severity_label(self, priority_score: float) -> str:
        for threshold, label in SEVERITY_LABELS:
            if priority_score >= threshold:
                return label
        return "low"

    def _repair_actions(self, *, dimension: str, questions: list[Question]) -> list[str]:
        prompt = questions[0].text
        if dimension == "backend_basic":
            return [
                f"围绕 `{prompt}` 写一版结构化答案并补齐缺失知识点。",
                "用 10 分钟复述关键概念，确保能解释原理而不是只背结论。",
            ]
        if dimension == "system_design":
            return [
                "按需求澄清、容量估算、架构与 trade-off 四步重做一次系统设计。",
                "把缓存、限流和扩展性方案整理成固定答题模板。",
            ]
        if dimension == "rag_llm":
            return [
                "补写 RAG/Agent 项目的评测指标和效果表达。",
                "准备 2 分钟项目口述，覆盖 pipeline、评测和权衡。",
            ]
        if dimension == "algorithm":
            return [
                "重做同类算法题，补充复杂度和边界情况说明。",
                "口述一遍解题思路，再写下优化点。",
            ]
        return [
            "补齐该维度的 STAR/结构化表达。",
            "做一次 10 分钟自我讲解并记录仍然卡顿的地方。",
        ]

    def _why_it_matters(self, *, dimension: str, jd_weight: float, questions: list[Question]) -> str:
        mastery = questions[0].latest_mastery_level
        if jd_weight >= 0.8:
            return f"目标 JD 明确强调 `{dimension}`，但当前历史作答仍处于 `{mastery}`，短期内会直接影响匹配度。"
        return f"该维度在历史作答中重复暴露短板，当前表现为 `{mastery}`，需要尽快形成稳定回答框架。"

    def _overall_risk(self, gaps: list[DiagnosedGap]) -> str:
        if not gaps:
            return "low"
        top = max(item.priority_score for item in gaps)
        if top >= 0.8:
            return "high"
        if top >= 0.45:
            return "medium"
        return "low"

    def _update_ability_scores(self, session: Session, *, user_id: str, gaps: list[DiagnosedGap]) -> None:
        for gap in gaps:
            score = max(1.0, round(5.0 - gap.priority_score * 4.0, 2))
            confidence = min(1.0, 0.6 + len(gap.evidence) * 0.1)
            self.repository.upsert_ability_score(
                session,
                user_id=user_id,
                dimension=gap.dimension,
                score=score,
                confidence=confidence,
            )
