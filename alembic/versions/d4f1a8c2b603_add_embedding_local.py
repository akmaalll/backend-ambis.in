"""add curriculum_chunks.embedding_local for the local fallback embedding model

Revision ID: d4f1a8c2b603
Revises: b7d41e9c8a52
Create Date: 2026-11-22

Second embedding space (Qwen3-Embedding-0.6B truncated to 768 dims), used when
Gemini embeddings are unavailable. Kept in its own column because vectors from
different models are not comparable; the existing `embedding` column and its
HNSW index are untouched. Filled by `python -m scripts.backfill_embeddings --space local`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f1a8c2b603"
down_revision: Union[str, None] = "b7d41e9c8a52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("alter table curriculum_chunks add column if not exists embedding_local vector(768)"))
    op.execute(
        sa.text(
            """
            create index if not exists curriculum_chunks_embedding_local_idx
              on curriculum_chunks using hnsw (embedding_local vector_cosine_ops)
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("drop index if exists curriculum_chunks_embedding_local_idx"))
    op.execute(sa.text("alter table curriculum_chunks drop column if exists embedding_local"))
