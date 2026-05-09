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


@dataclass(slots=True)
class _MergedCandidate:
    source_type: str
    document_id: str
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    base_score: float = 0.0
    lexical_score: float = 0.0
    prefers_question: bool = False


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
        jd_id: str | None = None,
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
        jd_document_id = self._resolve_jd_document_id(session=session, user_id=user_id, jd_id=jd_id)

        merged: dict[str, _MergedCandidate] = {}
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
                    metadata = dict(match.metadata)
                    if (
                        source_type == "jd"
                        and jd_document_id is not None
                        and str(metadata.get("document_id") or "") != jd_document_id
                    ):
                        continue
                    dedupe_key = self._dedupe_key(
                        chunk_id=metadata.get("chunk_id", ""),
                        question_id=metadata.get("question_id", ""),
                    )
                    candidate = merged.get(dedupe_key)
                    incoming = _MergedCandidate(
                        source_type=source_type,
                        document_id=metadata.get("document_id", ""),
                        chunk_id=metadata.get("chunk_id", ""),
                        text=match.text,
                        metadata=metadata,
                        base_score=match.score,
                        prefers_question=bool(metadata.get("question_id")),
                    )
                    merged[dedupe_key] = self._merge_candidate(candidate, incoming)

        lexical_source_types = [item for item in route.source_types if item in {"question", "resume", "jd"}]
        if session is not None and self.repository is not None and lexical_source_types:
            for variant in route.query_variants:
                lexical_matches = self.repository.lexical_search(
                    session,
                    user_id=user_id,
                    query_text=variant,
                    source_types=lexical_source_types,
                    limit=max(limit * 2, 8),
                )
                for index, match in enumerate(lexical_matches):
                    if match.source_type == "jd" and jd_document_id is not None and match.document_id != jd_document_id:
                        continue
                    normalized = 1.0 / (1.0 + max(match.rank, 0.0) + index * 0.05)
                    metadata = {
                        "source_type": match.source_type,
                        "document_id": match.document_id,
                        "chunk_id": match.chunk_id,
                        "question_id": match.question_id or "",
                        "dimension": match.dimension or "",
                        "topics_text": match.topics_text,
                    }
                    dedupe_key = self._dedupe_key(
                        chunk_id=match.chunk_id,
                        question_id=match.question_id or "",
                    )
                    candidate = merged.get(dedupe_key)
                    incoming = _MergedCandidate(
                        source_type=match.source_type,
                        document_id=match.document_id,
                        chunk_id=match.chunk_id,
                        text=match.text,
                        metadata=metadata,
                        lexical_score=normalized,
                        prefers_question=match.item_type == "question",
                    )
                    merged[dedupe_key] = self._merge_candidate(candidate, incoming)

        results = [
            EvidenceItem(
                source_type=item.source_type,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                text=item.text,
                score=rerank_score(
                    base_score=item.base_score,
                    lexical_score=item.lexical_score,
                    metadata=item.metadata,
                    text=item.text,
                    query_variants=route.query_variants,
                    dimension=route.dimension,
                    strategy=route.strategy,
                ),
                metadata_summary={
                    key: value
                    for key, value in item.metadata.items()
                    if key in {
                        "question_id",
                        "dimension",
                        "topics_text",
                        "accuracy_score",
                        "structure_score",
                        "depth_score",
                        "score_summary",
                    }
                },
            )
            for item in merged.values()
        ]
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
            "llm_foundations": ("transformer", "attention", "位置编码", "moe", "rwkv", "mamba", "decoder"),
            "post_training_alignment": ("lora", "qlora", "sft", "dpo", "rlhf", "ppo", "微调", "偏好", "训练数据", "蒸馏"),
            "llm_inference_serving": ("kv cache", "vllm", "量化", "显存", "推理", "吞吐", "时延", "batching", "prefill", "decode"),
            "rag_retrieval": ("rag", "召回", "重排", "embedding", "向量库", "knowledge graph", "知识图谱", "citation"),
            "agent_orchestration": ("agent", "workflow", "tool calling", "tools", "memory", "planning", "reflection", "human-in-the-loop"),
            "llm_evaluation": ("评测", "benchmark", "faithfulness", "groundedness", "hallucination", "judge", "win-rate"),
            "rag_llm": ("llm", "大模型"),
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

    def _dedupe_key(self, *, chunk_id: str, question_id: str) -> str:
        if question_id:
            return f"question:{question_id}"
        return f"chunk:{chunk_id}"

    def _merge_candidate(
        self,
        existing: _MergedCandidate | None,
        incoming: _MergedCandidate,
    ) -> _MergedCandidate:
        if existing is None:
            return incoming

        prefers_question = existing.prefers_question or incoming.prefers_question
        if incoming.prefers_question and not existing.prefers_question:
            existing.source_type = incoming.source_type
            existing.document_id = incoming.document_id
            existing.chunk_id = incoming.chunk_id
            existing.text = incoming.text
            existing.metadata = incoming.metadata
        existing.base_score = max(existing.base_score, incoming.base_score)
        existing.lexical_score = max(existing.lexical_score, incoming.lexical_score)
        if not prefers_question and incoming.base_score + incoming.lexical_score > existing.base_score + existing.lexical_score:
            existing.source_type = incoming.source_type
            existing.document_id = incoming.document_id
            existing.chunk_id = incoming.chunk_id
            existing.text = incoming.text
            existing.metadata = incoming.metadata
        existing.prefers_question = prefers_question
        return existing

    def _resolve_jd_document_id(self, *, session: Session | None, user_id: str, jd_id: str | None) -> str | None:
        if jd_id is None or session is None or self.repository is None:
            return None
        jd = self.repository.latest_target_jd(session, user_id=user_id, jd_id=jd_id)
        if jd is None:
            return None
        return jd.document_id or None
