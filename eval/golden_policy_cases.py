"""Golden cases for PolicyEngine.next_intervention.

PolicyEngine needs no LLM/network, so these are cheap to run in run_eval.py
alongside the grading/diagnosis sets — added now so a future rule-table edit
gets the same "run before the demo" regression check as the LLM-backed tools,
per the architecture's "run on every prompt/policy change" instruction.
Complements (does not replace) the exhaustive per-row tests in
tests/test_policy_engine.py.
"""
from app.tools.policy_engine import AttemptRecord, next_intervention

# (attempts_for_problem, misconception_seen_before, expected_kind)
GOLDEN_POLICY_CASES = [
    ([], False, "guiding_question"),
    (
        [AttemptRecord(error_type=None, misconception_code="ADDS_NUM_DENOM_DIRECTLY", is_correct=False)],
        False,
        "explanation",
    ),
    (
        [AttemptRecord(error_type=None, misconception_code="ADDS_NUM_DENOM_DIRECTLY", is_correct=False)],
        True,
        "explanation",
    ),
    (
        [AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False)],
        False,
        "hint",
    ),
    (
        [
            AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
        ],
        False,
        "explanation",
    ),
    (
        [
            AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="procedural", misconception_code=None, is_correct=False),
        ],
        False,
        "hint",
    ),
    (
        [
            AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="procedural", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="conceptual", misconception_code=None, is_correct=False),
        ],
        False,
        "worked_example",
    ),
    (
        [
            AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="procedural", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="conceptual", misconception_code=None, is_correct=False),
            AttemptRecord(error_type="conceptual", misconception_code=None, is_correct=False),
        ],
        False,
        "worked_example",
    ),
    (
        [
            AttemptRecord(error_type=None, misconception_code="WRONG_LCM", is_correct=False),
            AttemptRecord(error_type=None, misconception_code="WRONG_LCM", is_correct=False),
        ],
        True,
        "explanation",
    ),
    (
        [AttemptRecord(error_type="prerequisite", misconception_code=None, is_correct=False)],
        False,
        "hint",
    ),
]


def run_policy_golden_set() -> tuple[int, int]:
    """Returns (passed, total)."""
    passed = 0
    for attempts, seen_before, expected_kind in GOLDEN_POLICY_CASES:
        decision = next_intervention(attempts, seen_before)
        ok = decision.kind == expected_kind
        passed += int(ok)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] attempts={len(attempts)} seen_before={seen_before} "
              f"-> got={decision.kind} expected={expected_kind}")
    return passed, len(GOLDEN_POLICY_CASES)
