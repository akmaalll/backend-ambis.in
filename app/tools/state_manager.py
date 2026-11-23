"""StateManager — EWMA mastery/confidence/streak/misconception update.

Pure math (unit-testable) plus one atomic DB write. Per architecture §0
decision 9, the ONLY write this module makes to student_concept_state is a
single INSERT ... ON CONFLICT (student_id, concept_id) DO UPDATE statement —
never a Python read-then-write, since that would lose updates under
concurrent writers. See AMBIS_DB_Architecture.md §7.1-A-4 for the canonical
SQL this mirrors.

misconception_code (not misconception_id) is the interface here: attempts
.detected_misconception_id is a UUID, but student_concept_state
.misconception_counts is keyed by misconceptions.code (per the architecture's
own comment: `{misconception_code: n}`), and the upstream Diagnostician tool
already classifies in terms of closed-set codes — so no UUID lookup belongs
in this module.
"""
import json
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.runtime import StudentConceptState

EWMA_ALPHA = 0.3
CONFIDENCE_STEP = 0.15


def compute_initial_mastery(score: float) -> float:
    """Mirrors the DO UPDATE branch's `mastery` formula, applied against a
    virtual baseline of mastery=0 for the first-ever attempt on a concept:
    0 + ALPHA * (score - 0) == ALPHA * score.
    """
    return EWMA_ALPHA * score


def compute_initial_confidence() -> float:
    """Mirrors the DO UPDATE branch's `confidence` formula against a virtual
    baseline of confidence=0: min(1.0, 0 + CONFIDENCE_STEP).
    """
    return min(1.0, CONFIDENCE_STEP)


def compute_initial_streak(is_correct: bool) -> int:
    """Mirrors the DO UPDATE branch's `correct_streak` CASE against a virtual
    baseline of correct_streak=0.
    """
    return 1 if is_correct else 0


def compute_initial_misconception_counts(misconception_code: str | None) -> dict[str, int]:
    """Mirrors the DO UPDATE branch's `misconception_counts` jsonb_set bump
    against a virtual baseline of misconception_counts={}.
    """
    if misconception_code is None:
        return {}
    return {misconception_code: 1}


_UPSERT_SQL = """
    INSERT INTO student_concept_state
        (student_id, concept_id, mastery, confidence, total_attempts,
         correct_streak, misconception_counts, last_seen_at)
    VALUES
        (:student_id, :concept_id, :initial_mastery, :initial_confidence, 1,
         :initial_streak, CAST(:initial_counts AS jsonb), now())
    ON CONFLICT (student_id, concept_id) DO UPDATE SET
        mastery = student_concept_state.mastery
            + :alpha * (:score - student_concept_state.mastery),
        confidence = LEAST(1.0, student_concept_state.confidence + :confidence_step),
        total_attempts = student_concept_state.total_attempts + 1,
        correct_streak = CASE
            WHEN :score = 1 THEN student_concept_state.correct_streak + 1
            ELSE 0
        END,
        misconception_counts = CASE
            WHEN CAST(:misconception_code AS text) IS NOT NULL THEN jsonb_set(
                student_concept_state.misconception_counts,
                array[CAST(:misconception_code AS text)],
                to_jsonb(
                    COALESCE(
                        CAST(student_concept_state.misconception_counts ->> CAST(:misconception_code AS text) AS int),
                        0
                    ) + 1
                ),
                true
            )
            ELSE student_concept_state.misconception_counts
        END,
        last_seen_at = now()
    RETURNING *
"""


class StateManager:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update(
        self,
        student_id: UUID,
        concept_id: UUID,
        score: float,
        misconception_code: str | None,
    ) -> StudentConceptState:
        """Apply one attempt's evidence to a student's concept state.

        score: 1.0 for a correct attempt, 0.0 for incorrect (matches :score
            in the canonical UPSERT — also drives the EWMA mastery update and
            the correct_streak reset/increment).
        misconception_code: the misconceptions.code detected on this attempt,
            or None if none was detected.
        """
        is_correct = score == 1.0
        params = {
            "student_id": student_id,
            "concept_id": concept_id,
            "score": score,
            "misconception_code": misconception_code,
            "alpha": EWMA_ALPHA,
            "confidence_step": CONFIDENCE_STEP,
            "initial_mastery": compute_initial_mastery(score),
            "initial_confidence": compute_initial_confidence(),
            "initial_streak": compute_initial_streak(is_correct),
            "initial_counts": json.dumps(compute_initial_misconception_counts(misconception_code)),
        }
        result = await self.db.execute(sa.text(_UPSERT_SQL), params)
        row = result.mappings().one()
        await self.db.commit()
        return StudentConceptState(**dict(row))
