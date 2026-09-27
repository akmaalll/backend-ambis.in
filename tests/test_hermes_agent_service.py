"""Service-level tests for HermesAgentService — the real evidence-pipeline orchestration.

No live DB/LLM (same convention as every other tool test in this repo): the
tool instances the service constructs are swapped for fakes after
construction, and the attempt_repository functions hermes_agent.py imported
by name are monkeypatched at that import site.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.schemas.hermes import HermesAgentRequest
from app.api.v1.services import hermes_agent as hermes_agent_module
from app.api.v1.services.hermes_agent import HermesAgentService
from app.core.llm_client import LLMResponseError
from app.tools.intervention_generator import InterventionContent


class FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()


class FakeEvaluator:
    def __init__(self, result):
        self.result = result

    async def evaluate(self, exercise, student_answer):
        return self.result


class FakeDiagnostician:
    def __init__(self, code):
        self.code = code
        self.called = False

    async def diagnose(self, exercise, student_answer):
        self.called = True
        return self.code


class FakeInterventionGenerator:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.called_with = None

    async def generate(self, exercise, decision, student_answer=None, misconception_code=None):
        self.called_with = (decision.kind, student_answer, misconception_code)
        if self.error:
            raise self.error
        return self.content


class FakeStateManager:
    def __init__(self, mastery=0.3, confidence=0.15):
        self.mastery = mastery
        self.confidence = confidence
        self.called_with = None

    async def update(self, student_id, concept_id, score, misconception_code):
        self.called_with = (student_id, concept_id, score, misconception_code)
        return SimpleNamespace(mastery=self.mastery, confidence=self.confidence)


def _exercise(**overrides):
    defaults = dict(id=uuid4(), concept_id=uuid4(), kind="short_answer", correct_answer="5/12")
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_service(monkeypatch, *, eval_result, misconception_code=None, seen_before=False,
                    intervention_content=None, intervention_error=None):
    exercise = _exercise()
    session = SimpleNamespace(id=uuid4(), student_id=uuid4())
    problem = SimpleNamespace(id=uuid4(), session_id=session.id, exercise_id=exercise.id)

    async def fake_get_exercise(db, exercise_id):
        return exercise

    async def fake_get_or_create_session(db, session_id, student_id, mode):
        return session

    async def fake_get_or_create_problem(db, problem_id, session_id, exercise_id):
        return problem

    async def fake_next_attempt_number(db, problem_id):
        return 1

    async def fake_load_attempt_history(db, problem_id):
        return []

    async def fake_has_seen_misconception(db, student_id, concept_id, code):
        return seen_before

    async def fake_resolve_misconception_uuid(db, code):
        return uuid4() if code else None

    monkeypatch.setattr(hermes_agent_module, "get_exercise", fake_get_exercise)
    monkeypatch.setattr(hermes_agent_module, "get_or_create_session", fake_get_or_create_session)
    monkeypatch.setattr(hermes_agent_module, "get_or_create_problem", fake_get_or_create_problem)
    monkeypatch.setattr(hermes_agent_module, "next_attempt_number", fake_next_attempt_number)
    monkeypatch.setattr(hermes_agent_module, "load_attempt_history", fake_load_attempt_history)
    monkeypatch.setattr(hermes_agent_module, "has_seen_misconception", fake_has_seen_misconception)
    monkeypatch.setattr(hermes_agent_module, "resolve_misconception_uuid", fake_resolve_misconception_uuid)

    service = HermesAgentService(db=FakeDB(), llm_client=None)
    service.evaluator = FakeEvaluator(eval_result)
    service.diagnostician = FakeDiagnostician(misconception_code)
    service.intervention_generator = FakeInterventionGenerator(intervention_content, intervention_error)
    service.state_manager = FakeStateManager()
    return service


@pytest.mark.asyncio
async def test_correct_answer_skips_diagnostician_policy_and_intervention_generator(monkeypatch):
    eval_result = SimpleNamespace(is_correct=True, error_type=None)
    service = _build_service(monkeypatch, eval_result=eval_result)
    request = HermesAgentRequest(student_id=uuid4(), student_answer="5/12", exercise_id=uuid4())

    events = [event async for event in service._run_pipeline(request)]

    assert service.diagnostician.called is False
    tool_calls = [payload["tool_name"] for name, payload in events if name == "tool_call"]
    assert tool_calls == ["Evaluator.evaluate", "StateManager.update"]

    done_payload = next(payload for name, payload in events if name == "done")
    assert done_payload.is_correct is True
    assert done_payload.misconception_code is None
    assert done_payload.decision is None
    assert done_payload.intervention_text is None


@pytest.mark.asyncio
async def test_wrong_answer_with_misconception_calls_all_five_tools_in_order(monkeypatch):
    eval_result = SimpleNamespace(is_correct=False, error_type="conceptual")
    service = _build_service(
        monkeypatch,
        eval_result=eval_result,
        misconception_code="ADDS_NUM_DENOM_DIRECTLY",
        intervention_content=InterventionContent(text="Yuk kita bahas ulang..."),
    )
    request = HermesAgentRequest(student_id=uuid4(), student_answer="3/7", exercise_id=uuid4())

    events = [event async for event in service._run_pipeline(request)]

    assert service.diagnostician.called is True
    tool_calls = [payload["tool_name"] for name, payload in events if name == "tool_call"]
    assert tool_calls == [
        "Evaluator.evaluate",
        "Diagnostician.diagnose",
        "PolicyEngine.next_intervention",
        "InterventionGenerator.generate",
        "StateManager.update",
    ]

    done_payload = next(payload for name, payload in events if name == "done")
    assert done_payload.misconception_code == "ADDS_NUM_DENOM_DIRECTLY"
    assert done_payload.intervention_text == "Yuk kita bahas ulang..."
    assert service.state_manager.called_with[3] == "ADDS_NUM_DENOM_DIRECTLY"


@pytest.mark.asyncio
async def test_llm_failure_in_intervention_generator_still_reaches_state_manager(monkeypatch):
    eval_result = SimpleNamespace(is_correct=False, error_type="procedural")
    service = _build_service(
        monkeypatch,
        eval_result=eval_result,
        misconception_code=None,
        intervention_error=LLMResponseError("boom"),
    )
    request = HermesAgentRequest(student_id=uuid4(), student_answer="wrong", exercise_id=uuid4())

    events = [event async for event in service._run_pipeline(request)]

    done_payload = next(payload for name, payload in events if name == "done")
    assert service.state_manager.called_with is not None
    assert done_payload.intervention_text == done_payload.decision.reason


@pytest.mark.asyncio
async def test_state_manager_called_last(monkeypatch):
    eval_result = SimpleNamespace(is_correct=False, error_type="calculation")
    service = _build_service(
        monkeypatch,
        eval_result=eval_result,
        intervention_content=InterventionContent(text="Coba cek lagi."),
    )
    request = HermesAgentRequest(student_id=uuid4(), student_answer="wrong", exercise_id=uuid4())

    events = [event async for event in service._run_pipeline(request)]

    tool_result_names = [payload["tool_name"] for name, payload in events if name == "tool_result"]
    assert tool_result_names[-1] == "StateManager.update"
