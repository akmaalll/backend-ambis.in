"""Embedding with automatic fallback: Gemini first, local Qwen3 service when Gemini is unavailable.

The two models produce vectors in different spaces, so they live in separate
columns of curriculum_chunks (`embedding` = Gemini, `embedding_local` = Qwen3)
and a query is only ever compared against the column of the space that
embedded it. `embed()` therefore returns the space together with the vectors.

Fallback triggers on quota (429), server errors (5xx) and transport failures;
4xx such as a bad request or auth error are re-raised, since the local model
cannot fix them. With `embedding_local_url` empty there is no fallback.
"""
import logging

from app.core.config import settings
from app.core.llm_client import LLMClient, LLMResponseError

logger = logging.getLogger(__name__)

SPACE_COLUMN = {"gemini": "embedding", "local": "embedding_local"}

_local_client: LLMClient | None = None


def _get_local_client() -> LLMClient | None:
    global _local_client
    if not settings.embedding_local_url:
        return None
    if _local_client is None:
        _local_client = LLMClient(base_url=settings.embedding_local_url, api_key="local")
    return _local_client


def should_fallback(exc: LLMResponseError) -> bool:
    status = exc.status_code
    return status is None or status == 429 or status >= 500


class EmbeddingRouter:
    def __init__(self, primary: LLMClient, local: LLMClient | None = None):
        self.primary = primary
        self.local = local

    @classmethod
    def from_settings(cls, primary: LLMClient) -> "EmbeddingRouter":
        return cls(primary, _get_local_client())

    async def embed(self, texts: list[str], kind: str = "query") -> tuple[str, list[list[float]]]:
        """Return (space, vectors). `kind` is "query" or "document"; only the
        local model uses it (Qwen3 wants an instruction prefix on queries)."""
        try:
            vectors = await self.primary.embed(
                texts,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            )
            return "gemini", vectors
        except LLMResponseError as exc:
            if self.local is None or not should_fallback(exc):
                raise
            logger.warning("Gemini embedding unavailable (%s); falling back to local model", exc)

        vectors = await self.local.embed(
            texts,
            model=settings.embedding_local_model,
            dimensions=settings.embedding_dimensions,
            extra={"task": kind},
        )
        return "local", vectors
