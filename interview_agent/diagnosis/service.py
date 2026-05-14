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


LOW_SCORE_THRESHOLD = 3

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
    answer_quality_penalty: float = 0.0,
    jd_coverage_gap: float = 0.0,
    evidence_gap: float = 0.0,
    recency_pressure: float = 0.0,
) -> float:
    base = (
        jd_weight
        * weakness_severity
        * evidence_confidence
        * repeated_failure_factor
        * (1 - recent_improvement)
    )
    signal_boost = (
        answer_quality_penalty * 0.18
        + jd_coverage_gap * 0.12
        + evidence_gap * 0.08
        + recency_pressure * 0.06
    )
    return round(min(1.0, base + signal_boost), 4)


@dataclass(slots=True)
class GapSignals:
    latest_mastery: str
    mastery_severity: float
    answer_quality_penalty: float
    jd_weight: float
    jd_coverage_gap: float
    evidence_confidence: float
    evidence_gap: float
    repeated_failure_factor: float
    recent_improvement: float
    recency_pressure: float
    sample_gaps: list[str]
    score_summaries: list[str]
    low_score_fields: list[str]


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
            query_text = items[0].text
            evidence = self.retrieval.build_evidence_bundle(
                session,
                user_id=user_id,
                query_text=query_text,
                source_types=["resume", "jd", "question"],
                dimension=dimension,
                jd_id=jd.id if jd is not None else None,
                limit=4,
            )
            signals = self._build_gap_signals(
                session,
                dimension=dimension,
                questions=items,
                jd_requirements=jd.structured_requirements if jd else [],
                jd_weight=jd_weights.get(dimension, 0.45),
                evidence=evidence,
            )
            priority_score = compute_priority_score(
                jd_weight=signals.jd_weight,
                weakness_severity=signals.mastery_severity,
                evidence_confidence=signals.evidence_confidence,
                repeated_failure_factor=signals.repeated_failure_factor,
                recent_improvement=signals.recent_improvement,
                answer_quality_penalty=signals.answer_quality_penalty,
                jd_coverage_gap=signals.jd_coverage_gap,
                evidence_gap=signals.evidence_gap,
                recency_pressure=signals.recency_pressure,
            )
            severity = self._severity_label(priority_score)
            repair_actions = self._repair_actions(dimension=dimension, questions=items, signals=signals)
            why_it_matters = self._why_it_matters(dimension=dimension, signals=signals)
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
                    jd_id=jd.id if jd is not None else None,
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

    def current(
        self,
        session: Session,
        *,
        user_id: str,
        jd_id: str | None,
        limit: int,
    ) -> tuple[str, list[DiagnosedGap]]:
        records = self.repository.latest_gap_run(session, user_id=user_id, jd_id=jd_id, limit=limit)
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

    def _build_gap_signals(
        self,
        session: Session,
        *,
        dimension: str,
        questions: list[Question],
        jd_requirements: list[dict[str, Any]],
        jd_weight: float,
        evidence: list[EvidenceItem],
    ) -> GapSignals:
        mastery_values = [MASTERY_TO_SEVERITY.get(item.latest_mastery_level, 0.7) for item in questions]
        max_mastery = max(mastery_values, default=0.7)
        avg_mastery = sum(mastery_values) / max(len(mastery_values), 1)
        answer_quality_penalty, low_score_fields, score_summaries = self._answer_quality_signals(session, questions)
        mastery_severity = max(max_mastery * 0.7 + avg_mastery * 0.3, answer_quality_penalty)
        sample_gaps = self._sample_answer_gaps(session, questions)
        return GapSignals(
            latest_mastery=self._representative_mastery(questions),
            mastery_severity=min(1.0, mastery_severity),
            answer_quality_penalty=answer_quality_penalty,
            jd_weight=jd_weight,
            jd_coverage_gap=self._jd_coverage_gap(dimension=dimension, requirements=jd_requirements),
            evidence_confidence=self._evidence_confidence(evidence=evidence, questions=questions),
            evidence_gap=self._evidence_gap(evidence=evidence),
            repeated_failure_factor=self._repeated_failure_factor(questions=questions, sample_gaps=sample_gaps),
            recent_improvement=self._recent_improvement(questions),
            recency_pressure=self._recency_pressure(questions),
            sample_gaps=sample_gaps,
            score_summaries=score_summaries,
            low_score_fields=low_score_fields,
        )

    def _representative_mastery(self, questions: list[Question]) -> str:
        ordered = sorted(
            questions,
            key=lambda item: (
                item.last_answered_at is not None,
                item.last_answered_at or datetime.min,
            ),
            reverse=True,
        )
        return ordered[0].latest_mastery_level if ordered else "未评估"

    def _answer_quality_signals(self, session: Session, questions: list[Question]) -> tuple[float, list[str], list[str]]:
        penalties: list[float] = []
        low_fields: list[str] = []
        summaries: list[str] = []
        for question in questions:
            metadata = self._question_chunk_metadata(session, question)
            scores = {
                "accuracy": self._optional_score(metadata.get("accuracy_score")),
                "structure": self._optional_score(metadata.get("structure_score")),
                "depth": self._optional_score(metadata.get("depth_score")),
            }
            present_scores = [score for score in scores.values() if score is not None]
            if present_scores:
                penalties.append(1.0 - (sum(present_scores) / len(present_scores)) / 5.0)
            else:
                penalties.append(MASTERY_TO_SEVERITY.get(question.latest_mastery_level, 0.7))
            for name, score in scores.items():
                if score is not None and score < LOW_SCORE_THRESHOLD and name not in low_fields:
                    low_fields.append(name)
            summary = str(metadata.get("score_summary") or "").strip()
            if summary and summary not in summaries:
                summaries.append(summary)
        if not penalties:
            return 0.7, [], []
        return round(sum(penalties) / len(penalties), 4), low_fields[:3], summaries[:3]

    def _question_chunk_metadata(self, session: Session, question: Question) -> dict[str, Any]:
        if not question.source_chunk_id:
            return {}
        chunk = self.repository.get_document_chunk(session, chunk_id=question.source_chunk_id)
        if chunk is None:
            return {}
        return dict(chunk.metadata_json or {})

    def _optional_score(self, raw_value: Any) -> int | None:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return max(1, min(5, value))

    def _sample_answer_gaps(self, session: Session, questions: list[Question]) -> list[str]:
        gaps: list[str] = []
        for question in questions:
            for record in self.repository.list_answer_records_for_question(session, question_id=question.id)[:2]:
                for gap in record.gaps:
                    normalized = str(gap).strip()
                    if normalized and normalized not in gaps:
                        gaps.append(normalized)
        return gaps[:4]

    def _jd_coverage_gap(self, *, dimension: str, requirements: list[dict[str, Any]]) -> float:
        matching = [item for item in requirements if str(item.get("dimension") or "") == dimension]
        if not matching:
            return 0.15 if requirements else 0.25
        weights = [float(item.get("weight", 0.45)) for item in matching]
        avg_weight = sum(weights) / len(weights)
        return round(min(1.0, 0.35 + avg_weight * 0.45 + len(matching) * 0.05), 4)

    def _evidence_confidence(self, *, evidence: list[EvidenceItem], questions: list[Question]) -> float:
        source_types = {item.source_type for item in evidence}
        base = 0.55 + min(len(evidence), 4) * 0.08 + min(len(questions), 3) * 0.04
        base += len(source_types) * 0.04
        return round(min(1.0, base), 4)

    def _evidence_gap(self, *, evidence: list[EvidenceItem]) -> float:
        if not evidence:
            return 0.65
        source_types = {item.source_type for item in evidence}
        gap = 0.0
        if "resume" not in source_types:
            gap += 0.25
        if "jd" not in source_types:
            gap += 0.15
        if "question" not in source_types:
            gap += 0.1
        return round(min(0.65, gap), 4)

    def _repeated_failure_factor(self, *, questions: list[Question], sample_gaps: list[str]) -> float:
        weak_count = sum(1 for item in questions if item.latest_mastery_level != "熟练掌握")
        return round(min(1.7, 1.0 + max(weak_count - 1, 0) * 0.12 + len(sample_gaps) * 0.04), 4)

    def _recent_improvement(self, questions: list[Question]) -> float:
        if not questions:
            return 0.0
        mastered = sum(1 for item in questions if item.latest_mastery_level == "熟练掌握")
        if mastered == len(questions):
            return 0.35
        if mastered:
            return 0.15
        return 0.0

    def _recency_pressure(self, questions: list[Question]) -> float:
        answered = [item for item in questions if item.last_answered_at is not None]
        if not answered:
            return 0.25
        latest = max(answered, key=lambda item: item.last_answered_at or datetime.min)
        if latest.latest_mastery_level == "熟练掌握":
            return 0.0
        days = max((datetime.now() - (latest.last_answered_at or datetime.min)).days, 0)
        if days <= 3:
            return 0.6
        if days <= 14:
            return 0.4
        return 0.2

    def _severity_label(self, priority_score: float) -> str:
        for threshold, label in SEVERITY_LABELS:
            if priority_score >= threshold:
                return label
        return "low"

    def _repair_actions(
        self,
        *,
        dimension: str,
        questions: list[Question],
        signals: GapSignals | None = None,
    ) -> list[str]:
        prompt = questions[0].text
        score_action = self._score_repair_action(signals)
        if dimension == "backend_basic":
            return self._prepend_score_action([
                f"围绕 `{prompt}` 写一版结构化答案并补齐缺失知识点。",
                "用 10 分钟复述关键概念，确保能解释原理而不是只背结论。",
            ], score_action)
        if dimension == "system_design":
            return self._prepend_score_action([
                "按需求澄清、容量估算、架构与 trade-off 四步重做一次系统设计。",
                "把缓存、限流和扩展性方案整理成固定答题模板。",
            ], score_action)
        if dimension == "llm_foundations":
            return self._prepend_score_action([
                "把核心机制拆成结构、信息流、复杂度、trade-off 四段重写一版答案。",
                "针对同主题补一张原理对比表，例如 Attention vs 线性/稀疏变体。",
            ], score_action)
        if dimension == "post_training_alignment":
            return self._prepend_score_action([
                "补写该题涉及的训练目标、数据格式、可训练参数和关键超参。",
                "准备一版能说清 SFT / LoRA / DPO 等差异与适用场景的口述答案。",
            ], score_action)
        if dimension == "llm_inference_serving":
            return self._prepend_score_action([
                "围绕 prefill、decode、KV cache、batching、显存与吞吐 trade-off 重写答案。",
                "准备一个线上推理优化案例，能解释时延瓶颈和具体优化动作。",
            ], score_action)
        if dimension == "rag_retrieval":
            return self._prepend_score_action([
                "补写切分、索引、召回、重排、生成注入和评测指标六步链路。",
                "准备一版能说清 recall、precision、faithfulness 与幻觉控制的回答模板。",
            ], score_action)
        if dimension == "agent_orchestration":
            return self._prepend_score_action([
                "补写状态管理、工具调用、记忆、失败恢复和 human-in-the-loop 机制。",
                "用一个真实 agent workflow 例子讲清节点、边、终止条件和监控方式。",
            ], score_action)
        if dimension == "llm_evaluation":
            return self._prepend_score_action([
                "补写离线评测集、在线指标、judge 方案和回归监控机制。",
                "准备一版能区分效果指标、事实性指标和产品指标的结构化回答。",
            ], score_action)
        if dimension == "rag_llm":
            return self._prepend_score_action([
                "补写 RAG/Agent 项目的评测指标和效果表达。",
                "准备 2 分钟项目口述，覆盖 pipeline、评测和权衡。",
            ], score_action)
        if dimension == "algorithm":
            return self._prepend_score_action([
                "重做同类算法题，补充复杂度和边界情况说明。",
                "口述一遍解题思路，再写下优化点。",
            ], score_action)
        return self._prepend_score_action([
            "补齐该维度的 STAR/结构化表达。",
            "做一次 10 分钟自我讲解并记录仍然卡顿的地方。",
        ], score_action)

    def _score_repair_action(self, signals: GapSignals | None) -> str | None:
        if signals is None or not signals.low_score_fields:
            return None
        labels = {
            "accuracy": "准确性",
            "structure": "结构化表达",
            "depth": "展开深度",
        }
        fields = "、".join(labels.get(field, field) for field in signals.low_score_fields)
        return f"优先修复评分最低的 `{fields}`，重写答案时显式补结论、依据、例子和 trade-off。"

    def _prepend_score_action(self, actions: list[str], score_action: str | None) -> list[str]:
        if not score_action:
            return actions
        return [score_action, *actions][:3]

    def _why_it_matters(self, *, dimension: str, signals: GapSignals) -> str:
        pieces = [
            f"该维度当前表现为 `{signals.latest_mastery}`，综合短板强度 {signals.mastery_severity:.2f}。",
        ]
        if signals.jd_weight >= 0.8:
            pieces.append(f"目标 JD 明确强调 `{dimension}`（权重 {signals.jd_weight:.2f}），短期内会直接影响匹配度。")
        elif signals.jd_coverage_gap >= 0.45:
            pieces.append(f"JD 中已有明确相关要求，覆盖压力 {signals.jd_coverage_gap:.2f}。")
        if signals.answer_quality_penalty >= 0.45:
            pieces.append(f"历史作答评分暴露明显短板（质量缺口 {signals.answer_quality_penalty:.2f}）。")
        if signals.sample_gaps:
            pieces.append(f"高频缺口：{'；'.join(signals.sample_gaps[:2])}。")
        elif signals.score_summaries:
            pieces.append(f"评分反馈：{signals.score_summaries[0]}")
        if signals.evidence_gap >= 0.25:
            pieces.append(f"简历/JD/题库证据覆盖还不完整（证据缺口 {signals.evidence_gap:.2f}）。")
        if signals.recency_pressure >= 0.4:
            pieces.append("最近一次作答仍未稳定掌握，需要优先复盘。")
        return "".join(pieces)

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
