"""drop student_id foreign keys on the five pipeline tables

Revision ID: b7d41e9c8a52
Revises: e3c81f0a7d64
Create Date: 2026-10-04

Removes `<table>_student_id_fkey` from sessions, attempts, interventions,
student_concept_state and learning_paths.

This generalises a decision the schema already made once. a5eb4455c932 created
student_memories *without* a student_id foreign key and documented why: every
student-scoped table references profiles(id), profiles.id is itself
`references auth.users(id)` (554a024e01a9), and the demo/seed student
`00000000-0000-0000-0000-000000000901` — the id that DEFAULT_STUDENT_ID
(student_memory.py), the HermesAgentRequest default (schemas/hermes.py) and the
frontend all send — is never inserted into profiles by any migration. It cannot
be: a row in profiles needs a row in auth.users, which is managed by Supabase
Auth and not reachable from alembic.

That note scoped the fix to the one table it was adding. The five tables above
predate it and kept the FK, so the whole evidence pipeline inherited exactly the
failure the note predicted — scripts/smoke_hermes_pipeline.py dies on its first
INSERT:

    insert or update on table "sessions" violates foreign key constraint
    "sessions_student_id_fkey"
    DETAIL: Key (student_id)=(00000000-0000-0000-0000-000000000901) is not
            present in table "profiles".

Not RLS, not credentials — a foreign key, checked before either matters. No
anonymous student can be assessed, diagnosed or have mastery recorded while it
stands, which makes Assess -> Diagnose -> Intervene -> Reassess -> Adapt
unreachable in the product it is the core of. The FakeDB in
tests/test_hermes_agent_service.py enforces no constraints, which is why 82
green tests never surfaced it.

What is given up: the database no longer refuses an orphan student_id, and
`on delete cascade` no longer reaps pipeline rows when a profile is deleted. Both
are real losses, accepted on the same terms as a5eb4455c932 — the loose uuid is
the intended shape until real auth lands, at which point the right move is to
restore these FKs together with a backfill that gives every student a profiles
row. downgrade() restores them, but will fail unless such a backfill has run
first; that is deliberate, since silently dropping orphaned rows to satisfy a
downgrade would destroy evidence data.

Indexes are untouched: the FKs were declared inline and the supporting indexes
(idx_attempts_student_concept and friends) are separate objects that the planner
still needs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7d41e9c8a52"
down_revision: Union[str, None] = "e3c81f0a7d64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres named these implicitly when 554a024e01a9 declared the columns inline,
# so they all follow the <table>_<column>_fkey convention. `if exists` keeps the
# migration idempotent and lets it run against a database where a constraint was
# already dropped by hand during debugging.
_TABLES = (
    "sessions",
    "attempts",
    "interventions",
    "student_concept_state",
    "learning_paths",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            sa.text(
                f"alter table {table} "
                f"drop constraint if exists {table}_student_id_fkey"
            )
        )


def downgrade() -> None:
    # Will raise if any student_id has no profiles row — see the module docstring.
    for table in _TABLES:
        op.execute(
            sa.text(
                f"alter table {table} "
                f"add constraint {table}_student_id_fkey "
                f"foreign key (student_id) references profiles(id) on delete cascade"
            )
        )
