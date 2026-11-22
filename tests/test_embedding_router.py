"""Tests for EmbeddingRouter — Gemini first, local fallback on quota/server/transport errors."""
import httpx
import pytest

from app.core import embedding
from app.core.embedding import EmbeddingRouter, should_fallback
from app.core.llm_client import LLMClient, LLMResponseError


class FakeClient:
    def __init__(self, vectors=None, error=None):
        self.vectors = vectors or [[1.0, 0.0]]
        self.error = error
        self.calls: list[dict] = []

    async def embed(self, texts, model, dimensions=None, extra=None):
        self.calls.append({"texts": texts, "model": model, "dimensions": dimensions, "extra": extra})
        if self.error:
            raise self.error
        return self.vectors


def _err(status):
    return LLMResponseError("boom", status_code=status)


@pytest.mark.parametrize("status,expected", [(429, True), (500, True), (503, True), (None, True), (400, False), (401, False), (403, False)])
def test_should_fallback(status, expected):
    assert should_fallback(_err(status)) is expected


@pytest.mark.asyncio
async def test_uses_gemini_when_available():
    primary, local = FakeClient([[0.1, 0.2]]), FakeClient()
    space, vectors = await EmbeddingRouter(primary, local).embed(["q"])
    assert (space, vectors) == ("gemini", [[0.1, 0.2]])
    assert local.calls == []


@pytest.mark.asyncio
async def test_falls_back_to_local_on_429_with_task_and_local_model(monkeypatch):
    monkeypatch.setattr(embedding.settings, "embedding_local_model", "local-model")
    primary, local = FakeClient(error=_err(429)), FakeClient([[0.9, 0.1]])
    space, vectors = await EmbeddingRouter(primary, local).embed(["q"], kind="query")
    assert (space, vectors) == ("local", [[0.9, 0.1]])
    assert local.calls[0]["model"] == "local-model"
    assert local.calls[0]["extra"] == {"task": "query"}


@pytest.mark.asyncio
async def test_does_not_fall_back_on_client_error():
    primary, local = FakeClient(error=_err(400)), FakeClient()
    with pytest.raises(LLMResponseError):
        await EmbeddingRouter(primary, local).embed(["q"])
    assert local.calls == []


@pytest.mark.asyncio
async def test_reraises_when_no_local_service_configured():
    with pytest.raises(LLMResponseError):
        await EmbeddingRouter(FakeClient(error=_err(429)), None).embed(["q"])


@pytest.mark.asyncio
async def test_local_failure_propagates():
    with pytest.raises(LLMResponseError):
        await EmbeddingRouter(FakeClient(error=_err(429)), FakeClient(error=_err(None))).embed(["q"])


@pytest.mark.asyncio
async def test_llm_client_error_carries_status_code_and_extra_reaches_payload():
    seen = {}

    def handler(request):
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(429, json={"error": "quota"})

    client = LLMClient(base_url="http://fake/v1", api_key="k")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    with pytest.raises(LLMResponseError) as info:
        await client.embed(["x"], model="m", dimensions=768, extra={"task": "query"})
    assert info.value.status_code == 429
    assert seen["task"] == "query" and seen["dimensions"] == 768


def test_from_settings_has_no_local_when_url_empty(monkeypatch):
    monkeypatch.setattr(embedding.settings, "embedding_local_url", "")
    assert EmbeddingRouter.from_settings(FakeClient()).local is None


def test_space_columns_are_fixed_whitelist():
    assert embedding.SPACE_COLUMN == {"gemini": "embedding", "local": "embedding_local"}
