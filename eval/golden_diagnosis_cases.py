"""Golden diagnosis cases for Diagnostician.diagnose_freeform.

Same exercise/answers as golden_grading_cases.py (kept aligned on purpose —
the two tools reason over the same attempt), but here we assert the expected
misconception_code instead of correctness. Concept id matches the live seed
("Penjumlahan Pecahan Berpenyebut Beda", id ...0203), so run_eval.py needs a
real DB connection to fetch that concept's 3 misconceptions as candidates.
"""
from eval.golden_grading_cases import EXERCISE_404

# (student_answer, expected_misconception_code)
GOLDEN_DIAGNOSIS_CASES = [
    ("17/20", None),
    ("4/9", "ADDS_NUM_DENOM_DIRECTLY"),
    ("3/9", "ADDS_NUM_DENOM_DIRECTLY"),
    ("16/20", "WRONG_LCM"),
    ("34/40", "FORGETS_SIMPLIFY"),
    ("18/20", None),  # plain calculation slip, not a systematic misconception
    ("17/19", None),
    ("0", None),  # too far off to hypothesize a specific misconception
]

__all__ = ["GOLDEN_DIAGNOSIS_CASES", "EXERCISE_404"]
