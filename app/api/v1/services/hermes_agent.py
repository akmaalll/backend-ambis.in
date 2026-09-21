"""HermesAgentService — real orchestration of the 5 built Hermes tools.

Wires the evidence pipeline architecture §5 describes:
    student_answer -> Evaluator -> Diagnostician -> attempts INSERT
                    -> StateManager -> PolicyEngine -> interventions INSERT

See docs/TOOL_SIGNATURES.md for each tool's own contract; this module owns
only the call order, the attempts/interventions row writes, and turning the
whole thing into either an SSE stream or a single JSON response.

Scope: this only covers a caller that already knows exercise_id (no free-text
"what is this problem about" intent mapping — that tool doesn't exist yet).
ask.py/AskService is untouched.

On a CORRECT answer, no misconception lookup and no intervention is
generated — PolicyEngine's ladder is a mistake-count ladder (see
attempt_repository.load_attempt_history's docstring and
tests/test_policy_engine.py, where every fixture attempt is is_correct=False)
and there is nothing to remediate. Only Evaluator, the attempts INSERT, and
StateManager run in that case.
"""
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.hermes import HermesAgentRequest, HermesNonStreamResponse
from app.core.llm_client import LLMClient, LLMResponseError
from app.models.runtime import Attempt, Intervention
from app.tools.attempt_repository import (
    get_exercise,
    get_or_create_problem,
    get_or_create_session,
    has_seen_misconception,
    load_attempt_history,
    next_attempt_number,
    resolve_misconception_uuid,
)
from app.tools.diagnostician import Diagnostician
from app.tools.evaluator import Evaluator
from app.tools.intervention_generator import InterventionContent, InterventionGenerator
from app.tools.policy_engine import AttemptRecord, PolicyDecision, next_intervention
from app.tools.state_manager import StateManager

# The 4 kinds PolicyEngine can return today that InterventionGenerator handles.
# "difficulty_up" etc. (Learning Path kinds) have no text-generation step here
# — see InterventionGenerator.generate's own ValueError for anything else.
_CONTENT_KINDS = {"guiding_question", "hint", "explanation", "worked_example"}


@dataclass
class PipelineResult:
    session_id: UUID
    problem_id: UUID
    attempt_id: UUID
    attempt_number: int
    is_correct: bool
    error_type: str | None
    misconception_code: str | None
    decision: PolicyDecision | None
    intervention_text: str | None
    mastery: float
    confidence: float


class HermesAgentService:
    def __init__(self, db: AsyncSession, llm_client: LLMClient):
        self.db = db
        self.llm_client = llm_client
        self.evaluator = Evaluator(llm_client)
        self.diagnostician = Diagnostician(db, llm_client)
        self.intervention_generator = InterventionGenerator(db, llm_client)
        self.state_manager = StateManager(db)

    async def _run_pipeline(
        self, request: HermesAgentRequest
    ) -> AsyncGenerator[tuple[str, Any], None]:
        db = self.db

        exercise = await get_exercise(db, request.exercise_id) if request.exercise_id else None
        session = await get_or_create_session(db, request.session_id, request.student_id, request.mode)
        problem = await get_or_create_problem(db, request.problem_id, session.id, request.exercise_id)
        if exercise is None:
            if problem.exercise_id is None:
                raise ValueError(
                    f"problem {problem.id!r} has no exercise_id — ad_hoc problems are not "
                    "supported by this pipeline yet"
                )
            exercise = await get_exercise(db, problem.exercise_id)

        attempt_number = await next_attempt_number(db, problem.id)

        yield "thinking", {"thought": "Menilai jawaban siswa..."}
        yield "tool_call", {"tool_name": "Evaluator.evaluate"}
        eval_result = await self.evaluator.evaluate(exercise, request.student_answer)
        yield "tool_result", {
            "tool_name": "Evaluator.evaluate",
            "is_correct": eval_result.is_correct,
            "error_type": eval_result.error_type,
        }

        misconception_code: str | None = None
        decision: PolicyDecision | None = None

        if not eval_result.is_correct:
            yield "thinking", {"thought": "Mendiagnosis kemungkinan miskonsepsi..."}
            yield "tool_call", {"tool_name": "Diagnostician.diagnose"}
            misconception_code = await self.diagnostician.diagnose(exercise, request.student_answer)
            yield "tool_result", {
                "tool_name": "Diagnostician.diagnose",
                "misconception_code": misconception_code,
            }

            seen_before = False
            if misconception_code is not None:
                seen_before = await has_seen_misconception(
                    db, request.student_id, exercise.concept_id, misconception_code
                )

            history = await load_attempt_history(db, problem.id)
            history.append(
                AttemptRecord(
                    error_type=eval_result.error_type,
                    misconception_code=misconception_code,
                    is_correct=False,
                )
            )

            yield "thinking", {"thought": "Menentukan intervensi berikutnya..."}
            yield "tool_call", {"tool_name": "PolicyEngine.next_intervention"}
            decision = next_intervention(history, seen_before)
            yield "tool_result", {
                "tool_name": "PolicyEngine.next_intervention",
                "kind": decision.kind,
                "rule_code": decision.rule_code,
                "reason": decision.reason,
            }

        misconception_uuid = await resolve_misconception_uuid(db, misconception_code)
        attempt = Attempt(
            problem_id=problem.id,
            session_id=session.id,
            student_id=request.student_id,
            concept_id=exercise.concept_id,
            attempt_number=attempt_number,
            student_answer=request.student_answer,
            is_correct=eval_result.is_correct,
            error_type=eval_result.error_type,
            detected_misconception_id=misconception_uuid,
            time_spent_ms=request.time_spent_ms,
        )
        db.add(attempt)
        await db.flush()

        content: InterventionContent | None = None
        if decision is not None and decision.kind in _CONTENT_KINDS:
            yield "tool_call", {"tool_name": "InterventionGenerator.generate", "kind": decision.kind}
            try:
                content = await self.intervention_generator.generate(
                    exercise,
                    decision,
                    student_answer=request.student_answer if decision.kind == "hint" else None,
                    misconception_code=misconception_code,
                )
            except LLMResponseError:
                # A flaky LLM call for wording must never block the mastery-state
                # write below — fall back to the policy's own logged reason.
                content = InterventionContent(text=decision.reason)
            yield "tool_result", {"tool_name": "InterventionGenerator.generate", "text": content.text}

        if decision is not None:
            db.add(
                Intervention(
                    session_id=session.id,
                    student_id=request.student_id,
                    concept_id=exercise.concept_id,
                    attempt_id=attempt.id,
                    kind=decision.kind,
                    rule_code=decision.rule_code,
                    reason=decision.reason,
                    content={"text": content.text} if content else None,
                )
            )
            await db.flush()

        yield "tool_call", {"tool_name": "StateManager.update"}
        state = await self.state_manager.update(
            student_id=request.student_id,
            concept_id=exercise.concept_id,
            score=1.0 if eval_result.is_correct else 0.0,
            misconception_code=misconception_code,
        )
        yield "tool_result", {
            "tool_name": "StateManager.update",
            "mastery": state.mastery,
            "confidence": state.confidence,
        }

        if content is not None:
            words = content.text.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield "token", {"chunk": chunk, "index": i}

        yield "done", PipelineResult(
            session_id=session.id,
            problem_id=problem.id,
            attempt_id=attempt.id,
            attempt_number=attempt_number,
            is_correct=eval_result.is_correct,
            error_type=eval_result.error_type,
            misconception_code=misconception_code,
            decision=decision,
            intervention_text=content.text if content else None,
            mastery=state.mastery,
            confidence=state.confidence,
        )

    async def generate_stream(self, request: HermesAgentRequest) -> AsyncGenerator[str, None]:
        start = time.time()

        def format_sse(event: str, data: dict) -> str:
            # default=str: "done" payloads carry UUID values (session_id etc.), not JSON-native.
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

        try:
            async for event_name, payload in self._run_pipeline(request):
                if event_name == "done":
                    elapsed_ms = int((time.time() - start) * 1000)
                    yield format_sse("done", _build_done_payload(payload, elapsed_ms))
                else:
                    yield format_sse(event_name, payload)
        except ValueError as exc:
            yield format_sse("error", {"message": str(exc)})

    async def process_sync(self, request: HermesAgentRequest) -> HermesNonStreamResponse:
        start = time.time()
        result: PipelineResult | None = None
        async for event_name, payload in self._run_pipeline(request):
            if event_name == "done":
                result = payload
        assert result is not None  # _run_pipeline always ends with "done" or raises
        elapsed_ms = int((time.time() - start) * 1000)
        return HermesNonStreamResponse(**_build_done_payload(result, elapsed_ms))


def _build_done_payload(result: PipelineResult, processing_time_ms: int) -> dict:
    return {
        "session_id": result.session_id,
        "problem_id": result.problem_id,
        "attempt_id": result.attempt_id,
        "attempt_number": result.attempt_number,
        "is_correct": result.is_correct,
        "error_type": result.error_type,
        "misconception_code": result.misconception_code,
        "intervention": (
            {
                "kind": result.decision.kind,
                "rule_code": result.decision.rule_code,
                "reason": result.decision.reason,
                "text": result.intervention_text,
            }
            if result.decision is not None
            else None
        ),
        "mastery": result.mastery,
        "confidence": result.confidence,
        "processing_time_ms": processing_time_ms,
    }
