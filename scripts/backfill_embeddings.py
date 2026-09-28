"""One-off backfill: compute embeddings for curriculum_chunks rows missing one.

`curriculum_chunks.embedding` is deliberately NOT mapped in the CurriculumChunk
ORM model (see app/models/curriculum.py — pgvector ORM support is deferred), so
this script talks to that column via raw SQL only, same pattern as
StateManager's atomic UPSERT.

Provider: gemini-embedding-001 via 9router, truncated to 768 dims via the
`dimensions` param to match the existing vector(768) column with no schema
migration. See Decisions/2026-09-16 - Embedding model gemini-embedding-001 via
9router (vault) for why. LLMClient.embed() re-normalizes the truncated output
to unit length before this script ever sees it.

This is a manual script, not part of the test suite or CI — same category as
eval/run_eval.py. It writes to the real, shared Supabase DB, so run it
deliberately, not as a side effect of something else.

Usage:
    python -m scripts.backfill_embeddings
"""
import asyncio

import sqlalchemy as sa

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.llm_client import LLMClient

_SELECT_SQL = "SELECT id, content FROM curriculum_chunks WHERE embedding IS NULL ORDER BY id"
_UPDATE_SQL = "UPDATE curriculum_chunks SET embedding = CAST(:embedding AS vector) WHERE id = :id"


def _to_pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"


async def backfill() -> None:
    if not settings.llm_base_url:
        print(
            "SKIPPED — settings.llm_base_url is not configured.\n"
            "Fill LLM_BASE_URL / LLM_API_KEY into .env (see .env.example), then re-run."
        )
        return

    llm_client = LLMClient(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    try:
        async with async_session_factory() as db:
            rows = (await db.execute(sa.text(_SELECT_SQL))).all()
            if not rows:
                print("Nothing to backfill — no curriculum_chunks with a NULL embedding.")
                return

            print(f"Found {len(rows)} chunk(s) needing an embedding.")
            texts = [row.content for row in rows]
            vectors = await llm_client.embed(
                texts=texts,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            )

            for row, vector in zip(rows, vectors):
                await db.execute(
                    sa.text(_UPDATE_SQL),
                    {"id": row.id, "embedding": _to_pgvector_literal(vector)},
                )
                print(f"[OK] chunk {row.id} -> {len(vector)}-dim embedding stored")

            await db.commit()
            print(f"Done — backfilled {len(rows)} chunk(s).")
    finally:
        await llm_client.aclose()


def main() -> None:
    asyncio.run(backfill())


if __name__ == "__main__":
    main()
