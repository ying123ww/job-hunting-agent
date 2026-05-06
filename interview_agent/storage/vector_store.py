from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chromadb

from interview_agent.app.config import AppSettings
from interview_agent.app.providers import OpenAICompatibleProvider


COLLECTIONS = (
    "interview_chunks",
    "question_bank",
    "gap_memory",
    "episodic_memory",
)


@dataclass(slots=True)
class VectorMatch:
    vector_id: str
    text: str
    metadata: dict[str, Any]
    score: float


class ChromaVectorStore:
    def __init__(self, settings: AppSettings, provider: OpenAICompatibleProvider) -> None:
        self.provider = provider
        self.client = chromadb.PersistentClient(path=str(settings.chroma_path))
        self.collections = {
            name: self.client.get_or_create_collection(name=name)
            for name in COLLECTIONS
        }

    def upsert(
        self,
        *,
        collection_name: str,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        embeddings = self.provider.embed(texts)
        self.collections[collection_name].upsert(
            ids=ids,
            documents=texts,
            metadatas=[self._sanitize_metadata(item) for item in metadatas],
            embeddings=embeddings,
        )

    def query(
        self,
        *,
        collection_name: str,
        query_text: str,
        where: dict[str, Any] | None,
        limit: int,
    ) -> list[VectorMatch]:
        collection = self.collections[collection_name]
        result = collection.query(
            query_embeddings=self.provider.embed([query_text]),
            where=self._build_where(where),
            n_results=limit,
        )
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        matches: list[VectorMatch] = []
        for vector_id, text, metadata, distance in zip(ids, docs, metas, distances, strict=False):
            score = 1.0 / (1.0 + float(distance or 0.0))
            matches.append(VectorMatch(vector_id=vector_id, text=text, metadata=metadata or {}, score=score))
        return matches

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value
        return clean

    def _build_where(self, where: dict[str, Any] | None) -> dict[str, Any] | None:
        if not where:
            return None
        clauses = [{key: value} for key, value in where.items()]
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}
