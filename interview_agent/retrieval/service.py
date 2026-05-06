from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy.orm import Session

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
        source_types: Sequence[str],
        dimension: str | None = None,
        limit: int = 4,
    ) -> list[EvidenceItem]:
        source_filter = list(source_types)
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
                query_text=query_text,
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
                        score=self._rerank_score(match.score, match.metadata, dimension),
                        metadata_summary={
                            key: value
                            for key, value in match.metadata.items()
                            if key in {"question_id", "dimension", "topics_text"}
                        },
                    )
                )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

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
