"""Thin async client for 9router — an OpenAI-compatible LLM proxy.

Not Gemini (see Decisions/2026-09-15 - LLM provider adalah 9router, bukan
Gemini, in the vault) — this deliberately talks OpenAI chat-completions shape
over plain httpx (already a dependency), so no new SDK was needed.

Single-shot, constrained-JSON calls only — no streaming, no tool-calling.
Transient failures (timeouts, connection errors, 5xx) get a small manual
retry with backoff (no new dependency, e.g. `tenacity` — plain `asyncio.sleep`
is enough for this call volume); 4xx responses are not retried since retrying
a bad request/auth failure can't succeed.

Also exposes `embed()` for the same 9router instance's `/embeddings` endpoint
(see Decisions/2026-09-16 - Embedding model gemini-embedding-001 via 9router,
in the vault) — reuses the same connection pool and retry/backoff logic.
"""
import asyncio
import json
import math

import httpx

_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 0.5


class LLMResponseError(Exception):
    """Raised when 9router returns an HTTP error, a non-JSON body, or JSON
    that doesn't parse as an object. Callers (Evaluator/Diagnostician) decide
    what to do next — this class only reports that the contract was broken."""


def _normalize(vector: list[float]) -> list[float]:
    """L2-normalize a vector to unit length.

    9router's gemini-embedding-001 returns a unit vector at its native 3072
    dims, but the `dimensions`-truncated output (Matryoshka truncation) is
    NOT re-normalized server-side (measured norm ~0.567 at 768 dims). Cosine
    similarity — what curriculum_chunks' HNSW index uses — is scale-invariant,
    so this isn't required for correctness, but it keeps stored vectors
    consistent in case anything ever needs inner-product/L2 distance instead.
    """
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return vector
    return [x / norm for x in vector]


class LLMClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # One shared connection pool for the lifetime of this client, instead
        # of a fresh TCP+TLS handshake per call — call aclose() when done
        # (app shutdown, or end of a one-off script like eval/run_eval.py).
        self._client = httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post_with_retry(self, path: str, payload: dict) -> dict:
        """POST {base_url}{path} with the shared retry/backoff policy, return
        the parsed JSON response body. Shared by complete_json and embed."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}{path}"

        response: httpx.Response | None = None
        for attempt in range(_MAX_ATTEMPTS):
            is_last_attempt = attempt == _MAX_ATTEMPTS - 1
            try:
                response = await self._client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500 or is_last_attempt:
                    raise LLMResponseError(f"9router request to {path} failed: {exc}") from exc
            except httpx.HTTPError as exc:
                if is_last_attempt:
                    raise LLMResponseError(f"9router request to {path} failed: {exc}") from exc
            await asyncio.sleep(_BASE_BACKOFF_SECONDS * (2**attempt))

        assert response is not None  # loop always raises or breaks with a response
        content_type = response.headers.get("content-type", "")
        text = response.text
        if "text/event-stream" in content_type or text.lstrip().startswith("data:"):
            # Handle unexpected SSE stream gracefully by aggregating chunks
            aggregated_content = []
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if "content" in delta and delta["content"]:
                            aggregated_content.append(delta["content"])
                        msg = choices[0].get("message", {})
                        if "content" in msg and msg["content"]:
                            aggregated_content.append(msg["content"])
                except json.JSONDecodeError:
                    continue
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "".join(aggregated_content),
                        }
                    }
                ]
            }

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise LLMResponseError(f"9router returned invalid JSON: {exc}") from exc

    async def complete_json(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        """POST {base_url}/chat/completions with response_format=json_object,
        return the parsed JSON body of choices[0].message.content.

        response_format only guarantees the reply IS JSON, not its shape —
        callers must still validate the keys/values they expect.
        """
        import re

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        body = await self._post_with_retry("/chat/completions", payload)

        content = ""
        try:
            content = body["choices"][0]["message"]["content"]
            cleaned = content.strip()
            # Strip markdown fences e.g. ```json ... ``` or ``` ... ```
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned, strict=False)
        except (KeyError, IndexError, TypeError):
            raise LLMResponseError(f"9router response was not the expected format: {body!r}")
        except json.JSONDecodeError as exc:
            # Fallback: try to extract JSON object substring {...}
            match = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0), strict=False)
                except json.JSONDecodeError:
                    raise LLMResponseError(f"9router response was not valid JSON: {exc}") from exc
            else:
                raise LLMResponseError(f"9router response was not valid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise LLMResponseError(f"9router JSON content was not an object: {parsed!r}")

        return parsed

    async def embed(self, texts: list[str], model: str, dimensions: int | None = None) -> list[list[float]]:
        """POST {base_url}/embeddings, return one unit-normalized vector per
        input text, in the same order as `texts` (re-sorted by the response's
        own `index` field — the OpenAI shape does not guarantee row order).

        `dimensions` requests Matryoshka truncation (e.g. 768 to match
        curriculum_chunks.embedding's vector(768) column) — omit for the
        model's native dimensionality.
        """
        if not texts:
            return []

        payload: dict = {"model": model, "input": texts}
        if dimensions is not None:
            payload["dimensions"] = dimensions
        body = await self._post_with_retry("/embeddings", payload)

        try:
            rows = sorted(body["data"], key=lambda item: item["index"])
            vectors = [row["embedding"] for row in rows]
        except (KeyError, TypeError) as exc:
            raise LLMResponseError(f"9router embeddings response was not the expected shape: {exc}") from exc

        if len(vectors) != len(texts):
            raise LLMResponseError(
                f"9router returned {len(vectors)} embedding(s) for {len(texts)} input(s)"
            )

        return [_normalize(vector) for vector in vectors]
