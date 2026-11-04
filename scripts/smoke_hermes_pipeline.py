"""Smoke test: drive the Hermes evidence pipeline against the real database.

Every existing test of this pipeline (tests/test_hermes_agent_service.py) uses a
FakeDB, so they pin the *call order* of the five tools and nothing about the
transaction. This script answers the questions a FakeDB structurally cannot:

  - can the app's credentials actually INSERT into sessions, problems, attempts
    and interventions? Those tables have RLS enabled (554a024e01a9), and no code
    path has ever written to them — attempts has been sitting at 0 rows.
  - does StateManager's raw UPSERT behave on real Postgres, not just against a
    recorded-statement double?
  - does the whole thing commit, or does everything vanish at session close?
    _run_pipeline only ever calls flush(); the single commit lives at the end of
    StateManager.update(), which is why that call has to run last.

Why this works with no LLM credentials configured: for an `mcq` exercise both
Evaluator.evaluate and Diagnostician.diagnose take deterministic branches
(evaluate_mcq is a key comparison, diagnose_mcq is an options[].misconception_id
lookup). And on a CORRECT answer the pipeline skips PolicyEngine and
InterventionGenerator entirely. So scenario A below touches zero LLM calls.
Scenario B (a wrong MCQ answer) reaches InterventionGenerator, which does need
the LLM — but HermesAgentService catches LLMResponseError there and falls back to
the policy's own reason text, precisely so a flaky wording call cannot block the
mastery write. That fallback is itself worth exercising.

This is a manual script, not part of the test suite — same category as
eval/run_eval.py and scripts/backfill_embeddings.py. It WRITES to the real,
shared Supabase DB: one session, one problem, and one attempt row per scenario,
under the reserved seed/demo student id. Additive only, no deletes, no updates
to anything it did not create.

Usage:
    python -m scripts.smoke_hermes_pipeline
"""
import asyncio
import uuid

import sqlalchemy as sa

from app.api.deps import get_llm_client
from app.api.v1.schemas.hermes import HermesAgentRequest
from app.api.v1.services.hermes_agent import HermesAgentService
from app.core.database import async_session_factory

# Reserved seed/demo range, same convention as the seed migrations.
STUDENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000901")
EXERCISE_MCQ = uuid.UUID("00000000-0000-0000-0000-000000000401")  # 1/2 + 1/3, correct key B

# Option A on exercise 0401 is "2/5", tagged with misconception 0301
# (ADDS_NUM_DENOM_DIRECTLY) — the classic add-numerators-and-denominators error.
ANSWER_CORRECT = "B"
ANSWER_WRONG = "A"

_COUNTS_SQL = """
SELECT
  (SELECT count(*) FROM sessions)               AS sessions,
  (SELECT count(*) FROM problems)               AS problems,
  (SELECT count(*) FROM attempts)               AS attempts,
  (SELECT count(*) FROM interventions)          AS interventions,
  (SELECT count(*) FROM student_concept_state)  AS state
"""


async def _counts(db) -> dict:
    return dict((await db.execute(sa.text(_COUNTS_SQL))).mappings().one())


def _print_counts(label: str, counts: dict) -> None:
    body = "  ".join(f"{k}={v}" for k, v in counts.items())
    print(f"  {label:<8} {body}")


def _diff(before: dict, after: dict) -> str:
    parts = [f"{k} +{after[k] - before[k]}" for k in before if after[k] != before[k]]
    return ", ".join(parts) if parts else "NOTHING CHANGED"


async def _run_scenario(name: str, answer: str, expect_correct: bool) -> bool:
    """Returns True if the scenario's DB effects matched what the pipeline claimed."""
    print(f"\n--- {name} (answer={answer!r}) " + "-" * 30)
    llm_client = get_llm_client()

    async with async_session_factory() as db:
        before = await _counts(db)
        _print_counts("before", before)

    # A fresh session per scenario, mirroring the route: each request gets its
    # own AsyncSession, and the commit inside StateManager.update ends it.
    async with async_session_factory() as db:
        service = HermesAgentService(db, llm_client)
        request = HermesAgentRequest(
            student_id=STUDENT_ID,
            student_answer=answer,
            exercise_id=EXERCISE_MCQ,
            mode="ask",
            stream=False,
        )
        try:
            result = await service.process_sync(request)
        except Exception as exc:
            print(f"  FAILED  {type(exc).__name__}: {exc}")
            return False

    print(f"  claimed attempt_id={result.attempt_id} number={result.attempt_number}")
    print(f"          is_correct={result.is_correct} error_type={result.error_type}")
    print(f"          misconception={result.misconception_code}")
    if result.intervention is not None:
        iv = result.intervention
        print(f"          intervention kind={iv.kind} rule={iv.rule_code}")
        print(f"          text={iv.text[:100]!r}")
    else:
        print("          intervention=None (correct answer, nothing to remediate)")
    print(f"          mastery={result.mastery} confidence={result.confidence}")

    # The point of the whole script: re-read in a NEW session. If the pipeline
    # only flushed and never committed, the rows are gone by now and this shows
    # it, rather than the in-session identity map hiding it.
    async with async_session_factory() as db:
        after = await _counts(db)
        _print_counts("after", after)
        print(f"  delta   {_diff(before, after)}")

        persisted = (
            await db.execute(
                sa.text("SELECT count(*) FROM attempts WHERE id = CAST(:id AS uuid)"),
                {"id": str(result.attempt_id)},
            )
        ).scalar()

    ok = True
    if persisted != 1:
        print("  [FAIL] the attempt row it reported is NOT in the database — nothing committed")
        ok = False
    else:
        print("  [OK]   attempt row survives in a separate session — the write committed")

    if result.is_correct is not expect_correct:
        print(f"  [FAIL] expected is_correct={expect_correct}, got {result.is_correct}")
        ok = False

    if after["state"] == before["state"] and before["state"] == 0:
        print("  [FAIL] student_concept_state gained no row — StateManager's UPSERT did not land")
        ok = False
    else:
        print("  [OK]   student_concept_state written")

    return ok


async def _show_state() -> None:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                sa.text(
                    "SELECT concept_id::text AS cid, mastery, confidence, correct_streak, "
                    "       total_attempts, misconception_counts "
                    "FROM student_concept_state WHERE student_id = CAST(:sid AS uuid)"
                ),
                {"sid": str(STUDENT_ID)},
            )
        ).mappings().all()

    print("\n--- resulting student_concept_state " + "-" * 25)
    if not rows:
        print("  (no rows)")
        return
    for r in rows:
        print(f"  concept ...{r['cid'][-3:]}  mastery={r['mastery']}  conf={r['confidence']}")
        print(f"      streak={r['correct_streak']}  attempts={r['total_attempts']}")
        print(f"      misconception_counts={r['misconception_counts']}")


async def main() -> None:
    print("=" * 70)
    print("Hermes pipeline smoke test — WRITES to the live database")
    print(f"student_id  {STUDENT_ID}")
    print(f"exercise_id {EXERCISE_MCQ}  (mcq: no LLM needed to evaluate or diagnose)")
    print("=" * 70)

    # Wrong answer first, so the correct one lands second and the mastery/streak
    # movement between the two is visible in the final state dump.
    results = [
        await _run_scenario("B. wrong MCQ answer", ANSWER_WRONG, expect_correct=False),
        await _run_scenario("A. correct MCQ answer", ANSWER_CORRECT, expect_correct=True),
    ]

    await _show_state()

    print("\n" + "=" * 70)
    if all(results):
        print("RESULT: pipeline writes reach the database and survive the session.")
    else:
        print("RESULT: at least one scenario failed — see [FAIL] lines above.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
