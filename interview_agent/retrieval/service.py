from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy.orm import Session

from interview_agent.agent.memory import MemorySnapshot
from interview_agent.retrieval.query_rewriter import rewrite_query
from interview_agent.retrieval.reranker import rerank_score
from interview_agent.retrieval.source_router import infer_route
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
    query_variants: list[str]
    source_types: list[str]
    dimension: str | None
    strategy: str
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
        collections = ["interview_chunks"]
        if "question" in route.source_types:
            collections.append("question_bank")
        if "gap_record" in route.source_types:
            collections.append("gap_memory")

        deduped: dict[str, EvidenceItem] = {}
        for collection in collections:
            where: dict[str, Any] = {"user_id": user_id, "is_active": True}
            for variant in route.query_variants:
                matches = self.vector_store.query(
                    collection_name=collection,
                    query_text=variant,
                    where=where,
                    limit=limit,
                )
                for match in matches:
                    source_type = match.metadata.get("source_type", "unknown")
                    if route.source_types and source_type not in route.source_types:
                        continue
                    item = EvidenceItem(
                        source_type=source_type,
                        document_id=match.metadata.get("document_id", ""),
                        chunk_id=match.metadata.get("chunk_id", ""),
                        text=match.text,
                        score=rerank_score(
                            base_score=match.score,
                            metadata=match.metadata,
                            text=match.text,
                            query_variants=route.query_variants,
                            dimension=route.dimension,
                            strategy=route.strategy,
                        ),
                        metadata_summary={
                            key: value
                            for key, value in match.metadata.items()
                            if key in {"question_id", "dimension", "topics_text"}
                        },
                    )
                    dedupe_key = item.chunk_id or match.vector_id
                    existing = deduped.get(dedupe_key)
                    if existing is None or item.score > existing.score:
                        deduped[dedupe_key] = item

        results = list(deduped.values())
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
            strategy = "explicit"
            resolved_sources = requested_sources
            rationale = "explicit_source_types"
        else:
            plan = infer_route(query_text=query_text, intent=intent)
            strategy = plan.strategy
            resolved_sources = plan.source_types
            rationale = plan.rationale

        resolved_dimension = dimension or self._infer_dimension(query_text=query_text, memory_snapshot=memory_snapshot)
        variants = rewrite_query(
            query_text=query_text,
            intent=intent,
            dimension=resolved_dimension,
            memory_snapshot=memory_snapshot,
        )
        return RetrievalRoute(
            query_text=variants[-1] if variants else query_text,
            query_variants=variants or [query_text],
            source_types=resolved_sources,
            dimension=resolved_dimension,
            strategy=strategy,
            rationale=rationale,
        )

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
