"""add student_memories

Revision ID: a5eb4455c932
Revises: cdb08861f8b3
Create Date: 2026-09-27

Promotes `student_memories` from a runtime-created table to a real migration.

The table backs StudentMemoryService (app/api/v1/services/student_memory.py) —
the persistent cross-session chat memory (student's name, grade, goal, topic,
free-form facts, rolling summary) that the /chat routes inject into the Kak
Ambis system prompt. It was introduced by the chat feature as an idempotent
`CREATE TABLE IF NOT EXISTS` issued from `ensure_schema()` on every request,
which meant the schema could no longer be reproduced from alembic alone and
every chat call paid for a redundant DDL round-trip. This migration is the
authoritative definition; `ensure_schema()` is removed in the same change.

Raw SQL rather than op.create_table(), matching 554a024e01a9: the jsonb column
default (`'[]'::jsonb`), the RLS statement, and the updated_at trigger have no
clean SQLAlchemy ORM equivalent, and keeping the style uniform makes the three
migrations reviewable side by side. Plain op.execute(sa.text(...)) is safe here
(unlike cdb08861f8b3, which needed exec_driver_sql) because this DDL contains
no literal JSON — so there is no `:null` for sa.text() to misread as a bind
parameter.

Deliberately NOT declared: a foreign key on student_id. Every other
student-scoped table references profiles(id), but profiles.id itself is
`references auth.users(id)` (554a024e01a9), and the demo/seed student
`00000000-0000-0000-0000-000000000901` that DEFAULT_STUDENT_ID and the
frontend both send is never inserted into profiles by any migration. Adding
the FK would make every anonymous chat request fail on insert. StudentMemoryService
already degrades to a profiles lookup when a row is missing, so the loose
uuid primary key is the intended shape until real auth lands.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a5eb4455c932"
down_revision: Union[str, None] = "cdb08861f8b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            create table if not exists student_memories (
              student_id uuid primary key,
              name       text,
              grade      text,
              goal       text,
              topic      text,
              facts      jsonb default '[]'::jsonb,
              summary    text,
              updated_at timestamptz default now()
            )
            """
        )
    )

    # set_updated_at() is created by 554a024e01a9 and already drives
    # student_concept_state. Reusing it here means updated_at stays correct even
    # if a future writer forgets the explicit `updated_at = now()` that
    # StudentMemoryService.save_memory currently sets by hand.
    op.execute(
        sa.text(
            "drop trigger if exists trg_student_memories_updated on student_memories"
        )
    )
    op.execute(
        sa.text(
            """
            create trigger trg_student_memories_updated
              before update on student_memories
              for each row execute function set_updated_at()
            """
        )
    )

    # This table holds the most directly identifying data in the schema (a
    # student's name and grade), so it gets the same RLS posture as the other 16
    # tables — without it the row is reachable through the Supabase anon key.
    op.execute(sa.text("alter table student_memories enable row level security"))


def downgrade() -> None:
    op.execute(
        sa.text(
            "drop trigger if exists trg_student_memories_updated on student_memories"
        )
    )
    op.execute(sa.text("drop table if exists student_memories"))
