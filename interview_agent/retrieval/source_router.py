from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SourceRoutePlan:
    strategy: str
    source_types: list[str]
    rationale: str


def infer_route(*, query_text: str, intent: str | None) -> SourceRoutePlan:
    lowered = query_text.lower()
    if any(token in lowered for token in ("简历", "resume", "bullet", "项目经历", "项目怎么讲")):
        return SourceRoutePlan(
            strategy="resume_edit",
            source_types=["resume", "jd"],
            rationale="resume_jd_alignment",
        )
    if any(token in lowered for token in ("jd", "岗位", "职位", "匹配度", "岗位要求")):
        return SourceRoutePlan(
            strategy="jd_alignment",
            source_types=["jd", "resume", "gap_record"],
            rationale="jd_requirement_matching",
        )
    if any(token in lowered for token in ("今天", "today", "计划", "待办", "安排")) or intent == "plan":
        return SourceRoutePlan(
            strategy="planning",
            source_types=["gap_record", "question", "jd", "resume"],
            rationale="planning_gap_priority",
        )
    if any(token in lowered for token in ("短板", "gap", "诊断", "薄弱")) or intent == "diagnosis":
        return SourceRoutePlan(
            strategy="diagnosis",
            source_types=["gap_record", "question", "resume", "jd"],
            rationale="diagnosis_history_first",
        )
    if any(token in lowered for token in ("redis", "mysql", "epoll", "b+树", "八股", "算法", "系统设计")):
        return SourceRoutePlan(
            strategy="concept_qa",
            source_types=["question", "gap_record", "resume", "jd"],
            rationale="concept_history_and_evidence",
        )
    return SourceRoutePlan(
        strategy="general_qa",
        source_types=["resume", "jd", "question", "gap_record"],
        rationale="default_mixed_search",
    )
