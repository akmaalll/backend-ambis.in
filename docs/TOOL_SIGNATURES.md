# Hermes Tool Interfaces

For Dayat's orchestration loop (`app/api/v1/services/hermes_agent.py`). These five tools live in
`app/tools/` and are what Hermes calls at each step of a student attempt — the chassis (agent loop,
SSE streaming, session/turn management) is Dayat's; everything below the tool-call boundary is Ooka's.

All five are implemented and unit-tested (as of build-order item 4, on top of `da435ac`). None of them
are wired into `ask.py`/`hermes_agent.py` yet — both are still full mocks. That wiring is the next step,
and can start directly from the signatures below.

## Expected call order per student attempt

```
Evaluator.evaluate()
    -> Diagnostician.diagnose()          (only if the attempt was wrong)
    -> PolicyEngine.next_intervention()
    -> InterventionGenerator.generate()  (only if PolicyEngine returned one of the 4 content kinds
                                           below — "difficulty_up" etc. have no canvas to generate here)
    -> StateManager.update()
```

`Evaluator` and `Diagnostician` never see each other's output — both take the same
`(exercise, student_answer)` pair independently. `PolicyEngine` is pure (no DB/LLM) and only needs the
attempt history for the *current problem*. `InterventionGenerator` takes `PolicyEngine`'s decision
directly and turns it into a student-facing canvas (a `VisualSpec`, see `app/core/visual_spec.py`). `StateManager` is the only one that writes anything —
call it last, after content generation, so a slow/failed LLM call for the intervention canvas doesn't
block the mastery-state write.

## 1. `Evaluator` — grading (`app/tools/evaluator.py`)

```python
Evaluator(llm_client: LLMClient)

await evaluator.evaluate(exercise: Exercise, student_answer: str) -> EvaluationResult
# EvaluationResult(is_correct: bool, error_type: str | None)
# error_type is None iff is_correct is True; otherwise one of:
#   "calculation" | "procedural" | "conceptual" | "prerequisite"
```

- MCQ exercises: deterministic key match, no LLM call, `error_type` always `"conceptual"` when wrong
  (an MCQ distractor is always a tagged wrong rule, never a slip).
- Free-form/short-answer exercises: one LLM call via the grading-rubric prompt. That prompt only ever
  sees `{question, correct_answer, solution_steps, student_answer}` — never ladder/session/intervention
  context, so grading stays unbiased regardless of what the policy engine does next.
- Raises `ValueError` if `student_answer` is over 2000 chars, `LLMResponseError` if the LLM response
  doesn't parse into a valid result.

## 2. `Diagnostician` — misconception matching (`app/tools/diagnostician.py`)

```python
Diagnostician(db: AsyncSession, llm_client: LLMClient)

await diagnostician.diagnose(exercise: Exercise, student_answer: str) -> str | None
# returns a misconceptions.code, or None if no misconception was detected
```

- MCQ: looks up the selected option's tagged `misconception_id`, resolves it to a `code` — no LLM.
- Free-form: LLM proposes a hypothesis against the *closed set* of misconceptions tagged to that
  exercise's concept; accepted only on an exact code match, otherwise `None`. Never open-label.
- Same 2000-char guard and `LLMResponseError` behavior as `Evaluator`.

## 3. `PolicyEngine` — intervention ladder (`app/tools/policy_engine.py`)

```python
next_intervention(
    attempts_for_problem: list[AttemptRecord],   # AttemptRecord(error_type, misconception_code, is_correct)
    misconception_seen_before: bool,
) -> PolicyDecision
# PolicyDecision(kind: str, rule_code: str, reason: str)
# kind is one of: "guiding_question" | "hint" | "explanation" | "worked_example"
```

- Pure function — no DB, no LLM, no I/O. Safe to call directly, synchronously.
- `attempts_for_problem` must be scoped to the **current problem_id only** — the ladder resets per
  problem, it does not look across a whole session.
- `rule_code`/`reason` are for logging into `interventions`, not for display to the student.

## 4. `StateManager` — mastery/state update (`app/tools/state_manager.py`)

```python
StateManager(db: AsyncSession)

await state_manager.update(
    student_id: UUID,
    concept_id: UUID,
    score: float,                    # 1.0 if correct, 0.0 if incorrect
    misconception_code: str | None,  # None if none detected this attempt
) -> StudentConceptState
```

- One atomic `INSERT ... ON CONFLICT DO UPDATE` — never read-then-write from Python. Safe to call
  concurrently for different students/concepts.
- Updates EWMA mastery, confidence, correct streak, and bumps `misconception_counts` in one statement.
- Commits internally — call this last, after grading/diagnosis/policy are all resolved for the attempt.

## 5. `InterventionGenerator` — student-facing canvas (`app/tools/intervention_generator.py`)

```python
InterventionGenerator(db: AsyncSession, llm_client: LLMClient)

await intervention_generator.generate(
    exercise: Exercise,
    decision: PolicyDecision,               # straight from PolicyEngine.next_intervention()
    student_answer: str | None = None,      # optional extra grounding, "hint" kind only
    misconception_code: str | None = None,  # required when decision.kind == "explanation"
) -> InterventionContent
# InterventionContent(visual: VisualSpec)  -- stored as interventions.content -> {"visual": spec.to_payload()}
```

- Dispatches on `decision.kind`; only handles the four kinds `PolicyEngine` can return
  (`guiding_question` / `hint` / `explanation` / `worked_example`) — raises `ValueError` for any other
  kind (e.g. the Learning Path kinds `easier_exercise`/`prerequisite_review`/`difficulty_up`, which have
  no canvas-generation step here).
- One LLM call per invocation via the intervention prompt suite (`prompts/intervention_*.j2`, all
  sharing `prompts/_visual_spec_contract.j2`), SMP-VII tone. The LLM returns `{title, blocks}`;
  `intervention_kind` and `spec_version` are set by code, never trusted from the model.
- Output is validated by `parse_visual_spec` (schema, block types allowed per kind, arithmetic
  consistency, no final-answer leak). An invalid spec is retried **once** with the rejection reason
  appended; if it is still invalid, `LLMResponseError` is raised (same contract as
  `Evaluator`/`Diagnostician`), and the caller falls back to `fallback_note_spec`.
- **Never reveals the final answer**, at any rung — enforced in the system prompt, by the leak check on
  the finished spec (`exercise.correct_answer` in any equivalent numeric form) and, for
  `worked_example`, structurally: only `exercise.solution_steps[:-1]` is ever sent to the LLM, since by
  seed-data convention the last step states the literal answer.
- `explanation` looks up the misconception's `description`/`remediation_hint` plus a plain
  `concept_id`-scoped `curriculum_chunks` row (not vector search — real top-k RAG is item 5, only needed
  once Learning Path starts); raises `ValueError` if `misconception_code` doesn't resolve to a
  `misconceptions` row.
- Same 2000-char guard on `student_answer` (when passed to the `hint` kind) as `Evaluator`/`Diagnostician`.

## Wiring status

`app/api/v1/services/hermes_agent.py` (+ new `app/tools/attempt_repository.py`,
`app/api/deps.py`) now calls all five tools for real, end-to-end, for the "caller already
knows `exercise_id`" case described below. **Note for Dayat**: this means `hermes_agent.py` —
your chassis file — was modified out-of-band by Ooka for this task (same as every other
build-order item, this crossed the Dayat/Ooka file boundary once, on request, rather than
you having to do this wiring yourself). `app/api/v1/schemas/hermes.py` and
`app/api/v1/routes/hermes.py` were rewritten too; `tests/test_hermes.py`'s old
mock-contract tests were deleted and replaced by `tests/test_hermes_agent_service.py` +
`tests/test_attempt_repository.py`.

One behavior worth knowing before you build on top of this: **PolicyEngine.next_intervention()
is only called when the attempt is wrong.** Its ladder is a mistake-count ladder (`mistake_count
= len(attempts_for_problem)`, and every fixture in `tests/test_policy_engine.py` is
`is_correct=False`) — on a correct answer there's nothing to remediate, so the pipeline skips
Diagnostician, PolicyEngine, and InterventionGenerator entirely and goes straight from
Evaluator to the `attempts` INSERT and StateManager.update(). `attempt_repository.load_attempt_history()`
also filters to `is_correct=False` rows for the same reason — don't reuse it as a generic
"all attempts" fetch.

## SSE / response contract (canvas)

`hermes_agent.py` no longer streams `token` events. After `StateManager.update`, a wrong
attempt emits one `visual` event whose data is the whole VisualSpec (`app/core/visual_spec.py`,
contract in `AMBIS_Visual_Spec_Draft.md`), then `done`. `tool_result` for
`InterventionGenerator.generate` now carries `{tool_name, blocks}` (block count) instead of text.
`done` and `HermesNonStreamResponse.intervention` are `{kind, rule_code, reason, visual}`
(`visual` is `null` only if no content kind applied). On LLM failure or an invalid spec the
service substitutes a single `note` block holding `decision.reason`. `interventions.content` is
now `{"visual": {...}}`; rows written before this change hold `{"text": "..."}`.

## Not covered here (still open)

- Intent/concept-mapping from free text, `CurriculumRetriever` vector search, `ExerciseSelector`,
  `PathPlanner` — none of these tools exist yet. The current wiring requires the caller to already
  supply `exercise_id` (or an existing `problem_id`); it cannot infer "what problem is this" from
  a bare question.
- `ask.py`/`AskService` (free-text Q&A) — untouched, out of scope for the wiring task.
- `/sessions` / `/problems` CRUD routes — don't exist; the wiring auto-creates those rows inline
  when the caller omits `session_id`/`problem_id`.
- Live end-to-end smoke test against real Supabase + a filled-in LLM endpoint `.env` (Gemini) — flagged for a
  manual check, not run as part of this task (same carve-out as every other build-order item).
