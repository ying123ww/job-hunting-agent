from __future__ import annotations

import httpx
import pytest

from interview_agent.app.config import AppSettings
from interview_agent.app.providers import EmbeddingProviderError, OpenAICompatibleProvider


def test_embed_falls_back_to_local_hash_when_remote_request_fails(monkeypatch) -> None:
    settings = AppSettings(
        embedding_base_url="https://embeddings.example.test",
        embedding_api_key="secret",
        embedding_dimensions=8,
        embedding_strict=False,
    )
    provider = OpenAICompatibleProvider(settings=settings)

    def _raise_connect_error(self, *args, **kwargs):
        request = httpx.Request("POST", "https://embeddings.example.test/embeddings")
        raise httpx.ConnectError("dns failed", request=request)

    monkeypatch.setattr(httpx.Client, "post", _raise_connect_error)

    result = provider.embed(["hello world"])

    assert len(result) == 1
    assert len(result[0]) == 8
    assert all(isinstance(value, float) for value in result[0])


def test_embed_raises_when_strict_mode_is_enabled(monkeypatch) -> None:
    settings = AppSettings(
        embedding_base_url="https://embeddings.example.test",
        embedding_api_key="secret",
        embedding_dimensions=8,
        embedding_strict=True,
    )
    provider = OpenAICompatibleProvider(settings=settings)

    def _raise_connect_error(self, *args, **kwargs):
        request = httpx.Request("POST", "https://embeddings.example.test/embeddings")
        raise httpx.ConnectError("dns failed", request=request)

    monkeypatch.setattr(httpx.Client, "post", _raise_connect_error)

    with pytest.raises(EmbeddingProviderError) as exc_info:
        provider.embed(["hello world"])
    assert "cause=dns failed" in str(exc_info.value)


def test_embed_batches_remote_requests_by_ten(monkeypatch) -> None:
    settings = AppSettings(
        embedding_base_url="https://embeddings.example.test",
        embedding_api_key="secret",
        embedding_dimensions=4,
        embedding_strict=True,
    )
    provider = OpenAICompatibleProvider(settings=settings)
    calls: list[list[str]] = []

    class _Response:
        def __init__(self, batch: list[str]) -> None:
            self._batch = batch

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {"embedding": [float(index), 0.0, 0.0, 0.0]}
                    for index, _ in enumerate(self._batch, start=1)
                ]
            }

    def _post(self, url: str, *, json, headers):
        batch = list(json["input"])
        calls.append(batch)
        return _Response(batch)

    monkeypatch.setattr(httpx.Client, "post", _post)

    result = provider.embed([f"text-{index}" for index in range(11)])

    assert len(calls) == 2
    assert len(calls[0]) == 10
    assert len(calls[1]) == 1
    assert len(result) == 11
