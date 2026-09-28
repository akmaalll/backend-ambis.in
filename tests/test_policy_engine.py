from app.tools.policy_engine import AttemptRecord, next_intervention


def test_no_attempts_yet_gives_guiding_question():
    decision = next_intervention([], misconception_seen_before=False)
    assert decision.kind == "guiding_question"
    assert decision.rule_code == "INITIAL_PROMPT"


def test_misconception_detected_first_time_gives_explanation():
    attempts = [AttemptRecord(error_type="conceptual", misconception_code="ADDS_NUM_DENOM_DIRECTLY", is_correct=False)]
    decision = next_intervention(attempts, misconception_seen_before=False)
    assert decision.kind == "explanation"
    assert decision.rule_code == "MISCONCEPTION_DETECTED"


def test_misconception_detected_again_gives_explanation():
    attempts = [AttemptRecord(error_type="conceptual", misconception_code="ADDS_NUM_DENOM_DIRECTLY", is_correct=False)]
    decision = next_intervention(attempts, misconception_seen_before=True)
    assert decision.kind == "explanation"
    assert decision.rule_code == "REPEAT_MISCONCEPTION"


def test_first_mistake_no_misconception_gives_hint():
    attempts = [AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False)]
    decision = next_intervention(attempts, misconception_seen_before=False)
    assert decision.kind == "hint"
    assert decision.rule_code == "FIRST_MISTAKE_HINT"


def test_second_mistake_same_error_type_gives_explanation():
    attempts = [
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
    ]
    decision = next_intervention(attempts, misconception_seen_before=False)
    assert decision.kind == "explanation"
    assert decision.rule_code == "REPEAT_ERROR_EXPLANATION"


def test_second_mistake_different_error_type_gives_hint():
    attempts = [
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
        AttemptRecord(error_type="procedural", misconception_code=None, is_correct=False),
    ]
    decision = next_intervention(attempts, misconception_seen_before=False)
    assert decision.kind == "hint"
    assert decision.rule_code == "SECOND_MISTAKE_HINT"


def test_third_mistake_gives_worked_example():
    attempts = [
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
        AttemptRecord(error_type="procedural", misconception_code=None, is_correct=False),
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
    ]
    decision = next_intervention(attempts, misconception_seen_before=False)
    assert decision.kind == "worked_example"
    assert decision.rule_code == "REPEATED_MISTAKES_WORKED_EXAMPLE"


def test_fourth_plus_mistake_still_gives_worked_example():
    attempts = [
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False)
        for _ in range(5)
    ]
    decision = next_intervention(attempts, misconception_seen_before=False)
    assert decision.kind == "worked_example"
    assert decision.rule_code == "REPEATED_MISTAKES_WORKED_EXAMPLE"
