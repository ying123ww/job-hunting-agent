from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from interview_agent.app.config import AppSettings


logger = logging.getLogger(__name__)
REMOTE_EMBEDDING_BATCH_SIZE = 10


class EmbeddingProviderError(RuntimeError):
    pass


def _format_embedding_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        body = response.text.strip()
        suffix = f", body={body[:300]}" if body else ""
        return f"HTTP {response.status_code}{suffix}"
    if isinstance(exc, httpx.RequestError):
        return str(exc) or exc.__class__.__name__
    return str(exc) or exc.__class__.__name__


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vector: list[float] = []
    while len(vector) < dimensions:
        for value in digest:
            vector.append((value / 255.0) * 2.0 - 1.0)
            if len(vector) >= dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return vector


@dataclass(slots=True)
class OpenAICompatibleProvider:
    settings: AppSettings

    def has_real_chat(self) -> bool:
        return bool(self.settings.llm_base_url and self.settings.llm_api_key)

    def has_real_embeddings(self) -> bool:
        explicit = bool(self.settings.embedding_base_url and self.settings.embedding_api_key)
        inherited = bool(self.settings.llm_base_url and self.settings.llm_api_key)
        return explicit or inherited

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embedding_base_url = self.settings.embedding_base_url.strip()
        embedding_api_key = self.settings.embedding_api_key.strip()
        if embedding_base_url or embedding_api_key:
            if not embedding_base_url or not embedding_api_key:
                raise ValueError(
                    "INTERVIEW_AGENT_EMBEDDING_BASE_URL and "
                    "INTERVIEW_AGENT_EMBEDDING_API_KEY must be set together."
                )
        else:
            embedding_base_url = self.settings.llm_base_url.strip()
            embedding_api_key = self.settings.llm_api_key.strip()
        if not embedding_base_url or not embedding_api_key:
            return [
                _hash_embedding(text, self.settings.embedding_dimensions)
                for text in texts
            ]

        payload: dict[str, Any] = {
            "model": self.settings.llm_embedding_model,
            "input": texts,
        }
        if self.settings.embedding_dimensions > 0:
            payload["dimensions"] = self.settings.embedding_dimensions
        headers = {
            "Authorization": f"Bearer {embedding_api_key}",
            "Content-Type": "application/json",
        }
        try:
            embeddings: list[list[float]] = []
            with httpx.Client(timeout=30.0) as client:
                for start in range(0, len(texts), REMOTE_EMBEDDING_BATCH_SIZE):
                    batch = texts[start : start + REMOTE_EMBEDDING_BATCH_SIZE]
                    response = client.post(
                        f"{embedding_base_url.rstrip('/')}/embeddings",
                        json={
                            **payload,
                            "input": batch,
                        },
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()["data"]
                    embeddings.extend(item["embedding"] for item in data)
            return embeddings
        except Exception as exc:
            if self.settings.embedding_strict:
                raise EmbeddingProviderError(
                    "Remote embedding request failed while strict mode is enabled. "
                    f"endpoint={embedding_base_url.rstrip('/')}/embeddings, "
                    f"model={self.settings.llm_embedding_model}, cause={_format_embedding_error(exc)}"
                ) from exc
            logger.warning("Embedding request failed; falling back to local hash embeddings: %s", exc)
            return [
                _hash_embedding(text, self.settings.embedding_dimensions)
                for text in texts
            ]

    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if not self.has_real_chat():
            content = {
                "summary": "LLM fallback mode is active. Deterministic local heuristics are in use.",
                "system_prompt": system_prompt[:120],
                "user_prompt": user_prompt[:240],
            }
            return json.dumps(content, ensure_ascii=False)

        payload: dict[str, Any] = {
            "model": self.settings.llm_chat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
