from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy.orm import Session

from interview_agent.agent.memory import MemorySnapshot
from interview_agent.storage.repositories import InterviewRepository
from interview_agent.storage.vector_store import ChromaVectorStore


@dataclass(slots=True)
class EvidenceItem:
    source_type: str
    document_id: str
    chunk_id: str
    text: str
    score: float
    metadata_summary: dict[str, Any]


@dataclass(slots=True)
class RetrievalRoute:
    query_text: str
    source_types: list[str]
    dimension: str | None
    rationale: str


class RetrievalService:
    def __init__(
        self,
        *,
        repository: InterviewRepository,
        vector_store: ChromaVectorStore,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store

    def build_evidence_bundle(
        self,
        session: Session,
        *,
        user_id: str,
        query_text: str,
        source_types: Sequence[str] | None = None,
        dimension: str | None = None,
        intent: str | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        limit: int = 4,
    ) -> list[EvidenceItem]:
        route = self.route_request(
            query_text=query_text,
            source_types=list(source_types) if source_types is not None else None,
            dimension=dimension,
            intent=intent,
            memory_snapshot=memory_snapshot,
        )
        source_filter = route.source_types
        collections = ["interview_chunks"]
        if "question" in source_filter:
            collections.append("question_bank")
        if "gap_record" in source_filter:
            collections.append("gap_memory")

        results: list[EvidenceItem] = []
        for collection in collections:
            where: dict[str, Any] = {"user_id": user_id, "is_active": True}
            matches = self.vector_store.query(
                collection_name=collection,
                query_text=route.query_text,
                where=where,
                limit=limit,
            )
            for match in matches:
                if source_filter and match.metadata.get("source_type") not in source_filter:
                    continue
                results.append(
                    EvidenceItem(
                        source_type=match.metadata.get("source_type", "unknown"),
                        document_id=match.metadata.get("document_id", ""),
                        chunk_id=match.metadata.get("chunk_id", ""),
                        text=match.text,
                        score=self._rerank_score(match.score, match.metadata, route.dimension),
                        metadata_summary={
                            key: value
                            for key, value in match.metadata.items()
                            if key in {"question_id", "dimension", "topics_text"}
                        },
                    )
                )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def route_request(
        self,
        *,
        query_text: str,
        source_types: Sequence[str] | None = None,
        dimension: str | None = None,
        intent: str | None = None,
        memory_snapshot: MemorySnapshot | None = None,
    ) -> RetrievalRoute:
        requested_sources = [item for item in list(source_types or []) if item]
        if requested_sources:
            resolved_sources = requested_sources
            rationale = "explicit_source_types"
        else:
            resolved_sources, rationale = self._infer_sources(query_text=query_text, intent=intent)
        resolved_dimension = dimension or self._infer_dimension(query_text=query_text, memory_snapshot=memory_snapshot)
        expanded_query = self._expand_query(
            query_text=query_text,
            intent=intent,
            memory_snapshot=memory_snapshot,
            dimension=resolved_dimension,
        )
        return RetrievalRoute(
            query_text=expanded_query,
            source_types=resolved_sources,
            dimension=resolved_dimension,
            rationale=rationale,
        )

    def _infer_sources(self, *, query_text: str, intent: str | None) -> tuple[list[str], str]:
        lowered = query_text.lower()
        if any(token in lowered for token in ("简历", "resume", "bullet", "项目经历")):
            return ["resume", "jd"], "resume_jd"
        if any(token in lowered for token in ("jd", "岗位", "职位", "匹配度")):
            return ["jd", "resume", "gap_record"], "jd_focused"
        if any(token in lowered for token in ("题", "八股", "redis", "mysql", "b+树", "system design", "设计")):
            return ["question", "gap_record", "resume", "jd"], "question_focused"
        if intent in {"plan", "diagnosis", "sync"}:
            return ["gap_record", "question", "jd", "resume"], "planning_diagnosis"
        return ["resume", "jd", "question", "gap_record"], "default_mixed"

    def _infer_dimension(self, *, query_text: str, memory_snapshot: MemorySnapshot | None) -> str | None:
        lowered = query_text.lower()
        keyword_map = {
            "system_design": ("系统设计", "架构", "qps", "trade-off", "限流", "缓存"),
            "rag_llm": ("rag", "llm", "agent", "评测", "faithfulness", "recall@k"),
            "backend_basic": ("redis", "mysql", "epoll", "b+树", "数据库", "缓存"),
            "algorithm": ("算法", "链表", "树", "动态规划", "复杂度"),
            "behavioral": ("行为面", "自我介绍", "冲突", "优点", "缺点"),
        }
        for dimension, keywords in keyword_map.items():
            if any(keyword in lowered for keyword in keywords):
                return dimension
        if memory_snapshot and memory_snapshot.working_memory.latest_top_gap_dimensions:
            return memory_snapshot.working_memory.latest_top_gap_dimensions[0]
        return None

    def _expand_query(
        self,
        *,
        query_text: str,
        intent: str | None,
        memory_snapshot: MemorySnapshot | None,
        dimension: str | None,
    ) -> str:
        additions: list[str] = []
        if memory_snapshot is not None:
            working = memory_snapshot.working_memory
            if working.current_goal and working.current_goal not in query_text:
                additions.append(working.current_goal)
            if working.current_focus and working.current_focus not in query_text:
                additions.append(working.current_focus)
        if dimension and dimension not in query_text:
            additions.append(dimension)
        if intent and intent not in query_text:
            additions.append(f"intent:{intent}")
        if not additions:
            return query_text
        return "\n".join([query_text, *additions])

    def _rerank_score(
        self,
        base_score: float,
        metadata: dict[str, Any],
        dimension: str | None,
    ) -> float:
        score = base_score
        if dimension and metadata.get("dimension") == dimension:
            score += 0.15
        if metadata.get("source_type") in {"resume", "jd"}:
            score += 0.05
        return score
