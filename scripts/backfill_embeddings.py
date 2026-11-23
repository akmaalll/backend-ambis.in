"""One-off backfill: compute embeddings for curriculum_chunks rows missing one.

`curriculum_chunks.embedding` is deliberately NOT mapped in the CurriculumChunk
ORM model (see app/models/curriculum.py — pgvector ORM support is deferred), so
this script talks to that column via raw SQL only, same pattern as
StateManager's atomic UPSERT.

Provider: gemini-embedding-001 via the configured OpenAI-compatible endpoint
(Gemini), truncated to 768 dims via the `dimensions` param to match the
existing vector(768) column with no schema migration. See the vault Decision
"Embedding model gemini-embedding-001" (Projects/ambis-in) for why; the
embedding model is unchanged by the 9router removal, so existing vectors stay
compatible. LLMClient.embed() re-normalizes the truncated output
to unit length before this script ever sees it.

This is a manual script, not part of the test suite or CI — same category as
eval/run_eval.py. It writes to the real, shared Supabase DB, so run it
deliberately, not as a side effect of something else.

Usage:
    python -m scripts.backfill_embeddings                # Gemini -> embedding
    python -m scripts.backfill_embeddings --space local  # local Qwen3 service -> embedding_local
                                                         # (needs EMBEDDING_LOCAL_URL and local_embed/server.py running)
"""
import argparse
import asyncio

import sqlalchemy as sa

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.llm_client import LLMClient

_SELECT_SQL = "SELECT id, content FROM curriculum_chunks WHERE embedding IS NULL ORDER BY id"

# metadata - 'needs_embedding' drops that key, so the flag seeds set stops lying
# once the vector is actually there. `-` on jsonb is a no-op when the key is
# absent, so re-running this is safe.
_UPDATE_SQL = (
    "UPDATE curriculum_chunks "
    "SET embedding = CAST(:embedding AS vector), "
    "    metadata = metadata - 'needs_embedding' "
    "WHERE id = :id"
)


_LOCAL_SELECT_SQL = "SELECT id, content FROM curriculum_chunks WHERE embedding_local IS NULL ORDER BY id"
_LOCAL_UPDATE_SQL = "UPDATE curriculum_chunks SET embedding_local = CAST(:embedding AS vector) WHERE id = :id"
_LOCAL_BATCH = 4


def _to_pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"


async def backfill_local() -> None:
    """Fill curriculum_chunks.embedding_local from the local embedding service."""
    if not settings.embedding_local_url:
        print("SKIPPED — settings.embedding_local_url (EMBEDDING_LOCAL_URL) is not configured.")
        return

    client = LLMClient(base_url=settings.embedding_local_url, api_key="local", timeout=settings.embedding_local_timeout)
    try:
        async with async_session_factory() as db:
            rows = (await db.execute(sa.text(_LOCAL_SELECT_SQL))).all()
            if not rows:
                print("Nothing to backfill — no curriculum_chunks with a NULL embedding_local.")
                return

            print(f"Found {len(rows)} chunk(s) needing a local embedding.")
            for start in range(0, len(rows), _LOCAL_BATCH):
                batch = rows[start : start + _LOCAL_BATCH]
                vectors = await client.embed(
                    texts=[row.content for row in batch],
                    model=settings.embedding_local_model,
                    dimensions=settings.embedding_dimensions,
                    extra={"task": "document"},
                )
                for row, vector in zip(batch, vectors):
                    await db.execute(
                        sa.text(_LOCAL_UPDATE_SQL),
                        {"id": row.id, "embedding": _to_pgvector_literal(vector)},
                    )
                await db.commit()
                print(f"[OK] {start + len(batch)}/{len(rows)}")
            print(f"Done — backfilled {len(rows)} chunk(s) into embedding_local.")
    finally:
        await client.aclose()


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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--space", choices=["gemini", "local"], default="gemini")
    args = parser.parse_args()
    asyncio.run(backfill_local() if args.space == "local" else backfill())


if __name__ == "__main__":
    main()
