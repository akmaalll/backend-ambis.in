from app.tools.state_manager import (
    compute_initial_confidence,
    compute_initial_misconception_counts,
    compute_initial_mastery,
    compute_initial_streak,
)


def test_initial_mastery_correct_answer():
    assert compute_initial_mastery(1.0) == 0.3


def test_initial_mastery_incorrect_answer():
    assert compute_initial_mastery(0.0) == 0.0


def test_initial_confidence_is_fixed_step():
    assert compute_initial_confidence() == 0.15


def test_initial_streak_correct():
    assert compute_initial_streak(True) == 1


def test_initial_streak_incorrect():
    assert compute_initial_streak(False) == 0


def test_initial_misconception_counts_none():
    assert compute_initial_misconception_counts(None) == {}


def test_initial_misconception_counts_with_code():
    assert compute_initial_misconception_counts("ADDS_NUM_DENOM_DIRECTLY") == {
        "ADDS_NUM_DENOM_DIRECTLY": 1
    }
