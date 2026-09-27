"""Tests for LLMClient — retry/backoff and response parsing.

Uses httpx.MockTransport (part of httpx itself, no new dependency) instead of
a live 9router endpoint, so these stay in the "no live network in automated
tests" pattern used by the rest of the suite.
"""
import httpx
import pytest

from app.core.llm_client import LLMClient, LLMResponseError


def _client_with_handler(handler) -> LLMClient:
    client = LLMClient(base_url="http://fake-9router/v1", api_key="test-key")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    return client


async def _no_sleep(_seconds):
    return None


@pytest.mark.asyncio
async def test_complete_json_success_on_first_try():
    def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    client = _client_with_handler(handler)
    result = await client.complete_json("model", "sys", "user")
    assert result == {"ok": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_json_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.core.llm_client.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    client = _client_with_handler(handler)
    result = await client.complete_json("model", "sys", "user")
    assert calls["n"] == 3
    assert result == {"ok": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_json_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("app.core.llm_client.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        return httpx.Response(503)

    client = _client_with_handler(handler)
    with pytest.raises(LLMResponseError):
        await client.complete_json("model", "sys", "user")
    assert calls["n"] == 3  # _MAX_ATTEMPTS, no more
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_json_does_not_retry_on_4xx(monkeypatch):
    monkeypatch.setattr("app.core.llm_client.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        return httpx.Response(401)

    client = _client_with_handler(handler)
    with pytest.raises(LLMResponseError):
        await client.complete_json("model", "sys", "user")
    assert calls["n"] == 1  # never retried
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_json_rejects_non_json_content():
    def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    client = _client_with_handler(handler)
    with pytest.raises(LLMResponseError):
        await client.complete_json("model", "sys", "user")
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_json_reuses_the_same_underlying_client():
    def handler(_request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = _client_with_handler(handler)
    underlying = client._client
    await client.complete_json("model", "sys", "user")
    await client.complete_json("model", "sys", "user")
    assert client._client is underlying  # not recreated per call
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_returns_vectors_in_input_order():
    # Response rows deliberately out of order — client must sort by `index`.
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    client = _client_with_handler(handler)
    vectors = await client.embed(["first", "second"], model="gemini-embedding-001")
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_normalizes_truncated_vectors():
    # Not unit-length, mimicking 9router's un-normalized dimensions-truncated output.
    def handler(_request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [3.0, 4.0]}]})

    client = _client_with_handler(handler)
    vectors = await client.embed(["text"], model="gemini-embedding-001", dimensions=2)
    [vector] = vectors
    norm = sum(x * x for x in vector) ** 0.5
    assert vector == pytest.approx([0.6, 0.8])
    assert norm == pytest.approx(1.0)
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_empty_input_returns_empty_without_a_request():
    def handler(_request):
        raise AssertionError("should never be called for empty input")

    client = _client_with_handler(handler)
    vectors = await client.embed([], model="gemini-embedding-001")
    assert vectors == []
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_rejects_count_mismatch():
    def handler(_request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    client = _client_with_handler(handler)
    with pytest.raises(LLMResponseError):
        await client.embed(["a", "b"], model="gemini-embedding-001")
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_rejects_malformed_response():
    def handler(_request):
        return httpx.Response(200, json={"not_data": []})

    client = _client_with_handler(handler)
    with pytest.raises(LLMResponseError):
        await client.embed(["a"], model="gemini-embedding-001")
    await client.aclose()


@pytest.mark.asyncio
async def test_embed_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.core.llm_client.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    client = _client_with_handler(handler)
    vectors = await client.embed(["a"], model="gemini-embedding-001")
    assert calls["n"] == 3
    assert vectors == [[1.0, 0.0]]
    await client.aclose()
