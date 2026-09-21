"""Eval harness runner. See AMBIS_DB_Architecture.md §7.1-E.

Runs three golden sets and prints per-case pass/fail + an accuracy summary:
  - policy:    PolicyEngine.next_intervention — pure, no LLM/DB, always runs.
  - grading:   Evaluator.evaluate_freeform — needs a live 9router endpoint.
  - diagnosis: Diagnostician.diagnose_freeform — needs live 9router + live DB
               (to fetch the concept's misconceptions as candidates).

Meant to be run manually by the user once real 9router credentials are filled
into `.env` ("run on every prompt/policy change" per the architecture doc) —
not part of the Docker/pytest CI target, since it needs live network/DB access
that the sandboxed test container doesn't have.

Usage:
    python -m eval.run_eval
"""
import asyncio

from eval.golden_policy_cases import run_policy_golden_set


def _print_summary(name: str, passed: int, total: int) -> None:
    pct = (passed / total * 100) if total else 0.0
    print(f"\n{name}: {passed}/{total} passed ({pct:.0f}%)")


async def run_grading_and_diagnosis_golden_sets() -> None:
    from app.core.config import settings

    if not settings.llm_base_url:
        print(
            "\ngrading/diagnosis: SKIPPED — settings.llm_base_url is not configured yet.\n"
            "Fill LLM_BASE_URL / LLM_API_KEY / LLM_MODEL_GRADING / LLM_MODEL_DIAGNOSIS "
            "into .env (see .env.example), then re-run."
        )
        return

    from app.core.database import async_session_factory
    from app.core.llm_client import LLMClient
    from app.tools.diagnostician import Diagnostician
    from app.tools.evaluator import Evaluator
    from eval.golden_diagnosis_cases import GOLDEN_DIAGNOSIS_CASES
    from eval.golden_grading_cases import EXERCISE_404, GOLDEN_GRADING_CASES

    llm_client = LLMClient(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    try:
        print("\n--- grading ---")
        evaluator = Evaluator(llm_client=llm_client)
        grading_passed = 0
        for student_answer, expected_is_correct, expected_error_type in GOLDEN_GRADING_CASES:
            # One bad/flaky LLM call must not abort the rest of the golden set —
            # count it as a failure for this case and keep going.
            try:
                result = await evaluator.evaluate_freeform(EXERCISE_404, student_answer)
            except Exception as exc:  # noqa: BLE001 — deliberately broad, see comment above
                print(f"[FAIL] answer={student_answer!r} -> ERROR: {exc}")
                continue
            ok = result.is_correct == expected_is_correct and result.error_type == expected_error_type
            grading_passed += int(ok)
            status = "PASS" if ok else "FAIL"
            print(
                f"[{status}] answer={student_answer!r} -> got=({result.is_correct}, {result.error_type}) "
                f"expected=({expected_is_correct}, {expected_error_type})"
            )
        _print_summary("grading", grading_passed, len(GOLDEN_GRADING_CASES))

        print("\n--- diagnosis ---")
        async with async_session_factory() as db:
            diagnostician = Diagnostician(db=db, llm_client=llm_client)
            diagnosis_passed = 0
            for student_answer, expected_code in GOLDEN_DIAGNOSIS_CASES:
                try:
                    code = await diagnostician.diagnose_freeform(EXERCISE_404, student_answer)
                except Exception as exc:  # noqa: BLE001
                    print(f"[FAIL] answer={student_answer!r} -> ERROR: {exc}")
                    continue
                ok = code == expected_code
                diagnosis_passed += int(ok)
                status = "PASS" if ok else "FAIL"
                print(f"[{status}] answer={student_answer!r} -> got={code} expected={expected_code}")
        _print_summary("diagnosis", diagnosis_passed, len(GOLDEN_DIAGNOSIS_CASES))
    finally:
        await llm_client.aclose()


def main() -> None:
    print("--- policy ---")
    policy_passed, policy_total = run_policy_golden_set()
    _print_summary("policy", policy_passed, policy_total)

    asyncio.run(run_grading_and_diagnosis_golden_sets())


if __name__ == "__main__":
    main()
