"""PolicyEngine — the intervention ladder as a pure, deterministic function.

No DB, no LLM. Reasons only over attempts scoped to the CURRENT problem_id
(architecture §0 decision 7: attempt_number is scoped per problem, not per
session), per the rule table in AMBIS_DB_Architecture.md §3 step 4c.
"""
from dataclasses import dataclass


@dataclass
class AttemptRecord:
    """One prior attempt on the current problem, in the shape PolicyEngine needs."""
    error_type: str | None          # 'calculation'|'procedural'|'conceptual'|'prerequisite'
    misconception_code: str | None
    is_correct: bool


@dataclass
class PolicyDecision:
    kind: str        # matches interventions.kind CHECK constraint
    rule_code: str    # stable machine tag, matches interventions.rule_code
    reason: str       # free-text, matches interventions.reason


def next_intervention(
    attempts_for_problem: list[AttemptRecord],
    misconception_seen_before: bool,
) -> PolicyDecision:
    """Decide the next intervention for the current problem.

    attempts_for_problem: all attempts on THIS problem so far, in order.
    misconception_seen_before: whether the latest attempt's misconception_code
        (if any) already appears in student_concept_state.misconception_counts
        BEFORE this attempt was recorded.
    """
    if not attempts_for_problem:
        return PolicyDecision(
            kind="guiding_question",
            rule_code="INITIAL_PROMPT",
            reason="First attempt on this problem — prompt the student to start.",
        )

    latest = attempts_for_problem[-1]

    if latest.misconception_code is not None:
        if misconception_seen_before:
            return PolicyDecision(
                kind="explanation",
                rule_code="REPEAT_MISCONCEPTION",
                reason=f"Misconception '{latest.misconception_code}' detected again — re-explain the concept.",
            )
        return PolicyDecision(
            kind="explanation",
            rule_code="MISCONCEPTION_DETECTED",
            reason=f"Misconception '{latest.misconception_code}' detected for the first time — explain it.",
        )

    mistake_count = len(attempts_for_problem)

    if mistake_count == 1:
        return PolicyDecision(
            kind="hint",
            rule_code="FIRST_MISTAKE_HINT",
            reason="First mistake, no misconception tagged — give a hint.",
        )

    if mistake_count == 2:
        first_error_type = attempts_for_problem[0].error_type
        if latest.error_type == first_error_type:
            return PolicyDecision(
                kind="explanation",
                rule_code="REPEAT_ERROR_EXPLANATION",
                reason=f"Second mistake, same error_type ('{latest.error_type}') as the first — explain the concept.",
            )
        return PolicyDecision(
            kind="hint",
            rule_code="SECOND_MISTAKE_HINT",
            reason=f"Second mistake, different error_type ('{latest.error_type}' vs '{first_error_type}') — give another hint.",
        )

    return PolicyDecision(
        kind="worked_example",
        rule_code="REPEATED_MISTAKES_WORKED_EXAMPLE",
        reason=f"{mistake_count} mistakes on this problem — show a worked example.",
    )
