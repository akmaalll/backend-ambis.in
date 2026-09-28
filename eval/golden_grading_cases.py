"""Golden grading cases for Evaluator.evaluate_freeform.

All cases are against the seeded reassessment word-problem exercise
(exercises id 00000000-0000-0000-0000-000000000404, concept "Penjumlahan
Pecahan Berpenyebut Beda"): "Ibu punya 3/5 kg gula dan menambah 1/4 kg lagi.
Berapa total gula Ibu sekarang?" -> correct answer 17/20, in simplest form
(the question explicitly asks for simplest form, so an unsimplified-but-
numerically-equal answer is graded incorrect here — see FORGETS_SIMPLIFY
case below).

Kept intentionally small (~10 cases, not the architecture doc's original
~20) because the seed dataset currently has exactly one free-form exercise —
sized honestly against what's actually seeded rather than padded.
"""
from app.models.curriculum import Exercise

EXERCISE_404 = Exercise(
    kind="short_answer",
    concept_id="00000000-0000-0000-0000-000000000203",
    question=(
        "Ibu punya 3/5 kg gula dan menambah 1/4 kg lagi. Berapa total gula Ibu "
        "sekarang? (tulis dalam bentuk pecahan paling sederhana)"
    ),
    correct_answer="17/20",
    solution_steps=[
        "KPK dari 5 dan 4 = 20",
        "3/5 = 12/20, 1/4 = 5/20",
        "12/20 + 5/20 = 17/20",
        "17/20 sudah paling sederhana",
    ],
)

# (student_answer, expected_is_correct, expected_error_type)
GOLDEN_GRADING_CASES = [
    ("17/20", True, None),
    ("17/20 kg", True, None),
    ("4/9", False, "conceptual"),  # ADDS_NUM_DENOM_DIRECTLY: 3+1 / 5+4
    ("16/20", False, "conceptual"),  # WRONG_LCM: 1/4 miscoverted to 4/20 instead of 5/20
    ("34/40", False, "procedural"),  # FORGETS_SIMPLIFY: correct value, not simplest form
    ("18/20", False, "calculation"),  # arithmetic slip, right method
    ("17/19", False, "calculation"),  # arithmetic slip in the sum
    ("3/9", False, "conceptual"),  # ADDS_NUM_DENOM_DIRECTLY variant
    ("0", False, "conceptual"),  # nonsensical / no attempt at the method
    ("7/9", False, "conceptual"),  # wrong denominator handling, not a simple slip
]
