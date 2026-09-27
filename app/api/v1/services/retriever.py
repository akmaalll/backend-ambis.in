import logging
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    id: UUID
    concept_id: UUID
    content: str
    similarity: float
    metadata: dict


class CurriculumRetriever:
    """Retrieves relevant curriculum knowledge chunks from PostgreSQL using pgvector HNSW."""

    def __init__(self, db: AsyncSession, llm_client: LLMClient):
        self.db = db
        self.llm_client = llm_client

    async def search(self, query: str, top_k: int = 2, threshold: float = 0.65) -> list[RetrievedChunk]:
        """Search curriculum_chunks table using cosine similarity against the query embedding."""
        if not query or not query.strip():
            return []

        try:
            vectors = await self.llm_client.embed(
                texts=[query.strip()],
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            )
            if not vectors:
                return []

            vec_literal = "[" + ",".join(str(x) for x in vectors[0]) + "]"

            sql = """
                SELECT id, concept_id, content, metadata,
                       round((1 - (embedding <=> CAST(:vec AS vector)))::numeric, 4) as similarity
                FROM curriculum_chunks
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :limit;
            """
            result = await self.db.execute(
                sa.text(sql),
                {"vec": vec_literal, "limit": top_k},
            )
            rows = result.fetchall()

            chunks: list[RetrievedChunk] = []
            for row in rows:
                sim = float(row.similarity)
                if sim >= threshold:
                    chunks.append(
                        RetrievedChunk(
                            id=row.id,
                            concept_id=row.concept_id,
                            content=row.content,
                            similarity=sim,
                            metadata=row.metadata if isinstance(row.metadata, dict) else {},
                        )
                    )
            return chunks
        except Exception as exc:
            logger.warning("CurriculumRetriever search failed gracefully: %s", exc)
            return []
