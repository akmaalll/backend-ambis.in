"""Attempt/session/problem repository — DB glue for the Hermes evidence pipeline.

Not one of the 5 tool contracts documented in docs/TOOL_SIGNATURES.md. Evaluator,
Diagnostician, PolicyEngine, InterventionGenerator, and StateManager each operate
on data handed to them and don't touch sessions/problems/attempt-history rows
themselves (see their own docstrings) — this module is the id<->code mapping
and session/problem bootstrapping that app/api/v1/services/hermes_agent.py needs
in order to call those five tools against real request data.

All functions here take an AsyncSession and do not commit — the caller
(HermesAgentService) controls the transaction boundary, since StateManager.update()
is the one call in the pipeline that commits, and it must run last.
"""
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curriculum import Exercise, Misconception
from app.models.runtime import Attempt, Problem, Session, StudentConceptState
from app.tools.policy_engine import AttemptRecord


async def get_exercise(db: AsyncSession, exercise_id: UUID) -> Exercise:
    result = await db.execute(sa.select(Exercise).where(Exercise.id == exercise_id))
    exercise = result.scalar_one_or_none()
    if exercise is None:
        raise ValueError(f"no exercises row found for id={exercise_id!r}")
    return exercise


async def get_or_create_session(
    db: AsyncSession, session_id: UUID | None, student_id: UUID, mode: str
) -> Session:
    """Load an existing session, or start a new one.

    When session_id is given, it must belong to student_id — otherwise one
    student's request could write attempts/interventions into another
    student's session.
    """
    if session_id is not None:
        result = await db.execute(sa.select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            raise ValueError(f"no sessions row found for id={session_id!r}")
        if session.student_id != student_id:
            raise ValueError(f"session {session_id!r} does not belong to student {student_id!r}")
        return session

    session = Session(student_id=student_id, mode=mode, status="active")
    db.add(session)
    await db.flush()
    return session


async def get_or_create_problem(
    db: AsyncSession, problem_id: UUID | None, session_id: UUID, exercise_id: UUID | None
) -> Problem:
    """Load an existing problem, or start a new exercise-backed one.

    Only the 'exercise' problem shape is supported here — 'ad_hoc' problems
    (free-text, no exercise_id) need intent/concept-mapping, which is out of
    scope until that tool exists (see docs/TOOL_SIGNATURES.md's "Not covered
    here" section and the wiring task's scope boundary).
    """
    if problem_id is not None:
        result = await db.execute(sa.select(Problem).where(Problem.id == problem_id))
        problem = result.scalar_one_or_none()
        if problem is None:
            raise ValueError(f"no problems row found for id={problem_id!r}")
        if problem.session_id != session_id:
            raise ValueError(f"problem {problem_id!r} does not belong to session {session_id!r}")
        return problem

    if exercise_id is None:
        raise ValueError("exercise_id is required to create a new problem")

    exercise = await get_exercise(db, exercise_id)
    problem = Problem(
        session_id=session_id,
        concept_id=exercise.concept_id,
        source="exercise",
        exercise_id=exercise_id,
    )
    db.add(problem)
    await db.flush()
    return problem


async def next_attempt_number(db: AsyncSession, problem_id: UUID) -> int:
    result = await db.execute(
        sa.select(sa.func.coalesce(sa.func.max(Attempt.attempt_number), 0)).where(
            Attempt.problem_id == problem_id
        )
    )
    return result.scalar_one() + 1


async def load_attempt_history(db: AsyncSession, problem_id: UUID) -> list[AttemptRecord]:
    """Prior WRONG attempts on this problem, in PolicyEngine's AttemptRecord shape.

    Filtered to is_correct=False: PolicyEngine's ladder (see
    tests/test_policy_engine.py) is a mistake-count ladder — mistake_count is
    literally len(attempts_for_problem) — so a correct attempt must never be
    counted here. This also means the caller must not call next_intervention()
    at all once the current attempt is correct; see hermes_agent.py.
    """
    result = await db.execute(
        sa.select(Attempt.error_type, Misconception.code)
        .outerjoin(Misconception, Misconception.id == Attempt.detected_misconception_id)
        .where(Attempt.problem_id == problem_id, Attempt.is_correct.is_(False))
        .order_by(Attempt.attempt_number)
    )
    return [
        AttemptRecord(error_type=row.error_type, misconception_code=row.code, is_correct=False)
        for row in result
    ]


async def has_seen_misconception(
    db: AsyncSession, student_id: UUID, concept_id: UUID, misconception_code: str
) -> bool:
    """Whether this misconception was already counted for this student+concept.

    Must be read BEFORE StateManager.update() runs for the current attempt —
    StateManager bumps misconception_counts as part of that same call, so
    reading it after would always report True.
    """
    result = await db.execute(
        sa.select(StudentConceptState.misconception_counts).where(
            StudentConceptState.student_id == student_id,
            StudentConceptState.concept_id == concept_id,
        )
    )
    counts = result.scalar_one_or_none()
    if counts is None:
        return False
    return counts.get(misconception_code, 0) > 0


async def resolve_misconception_uuid(db: AsyncSession, code: str | None) -> UUID | None:
    if code is None:
        return None
    result = await db.execute(sa.select(Misconception.id).where(Misconception.code == code))
    resolved = result.scalar_one_or_none()
    if resolved is None:
        raise ValueError(f"no misconceptions row found for code={code!r}")
    return resolved
