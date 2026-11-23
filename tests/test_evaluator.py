import pytest

from app.core.llm_client import LLMResponseError
from app.models.curriculum import Exercise
from app.tools.evaluator import Evaluator, EvaluationResult


class FakeLLMClient:
    """Stub LLMClient — returns a canned response, never touches the network."""

    def __init__(self, response: dict):
        self.response = response

    async def complete_json(self, model, system_prompt, user_prompt):
        return self.response


def _mcq_exercise(correct_answer="B") -> Exercise:
    return Exercise(kind="mcq", question="2/3 + 1/4?", correct_answer=correct_answer)


def _freeform_exercise() -> Exercise:
    return Exercise(
        kind="short_answer",
        question="Berapa hasil dari 2/3 + 1/4?",
        correct_answer="11/12",
        solution_steps=None,
    )


def test_mcq_correct_answer():
    evaluator = Evaluator(llm_client=None)
    result = evaluator.evaluate_mcq(_mcq_exercise("B"), "B")
    assert result == EvaluationResult(is_correct=True, error_type=None)


def test_mcq_correct_answer_case_insensitive():
    evaluator = Evaluator(llm_client=None)
    result = evaluator.evaluate_mcq(_mcq_exercise("B"), "b")
    assert result.is_correct is True


def test_mcq_wrong_answer_defaults_to_conceptual():
    evaluator = Evaluator(llm_client=None)
    result = evaluator.evaluate_mcq(_mcq_exercise("B"), "A")
    assert result == EvaluationResult(is_correct=False, error_type="conceptual")


@pytest.mark.asyncio
async def test_freeform_correct():
    llm_client = FakeLLMClient({"is_correct": True, "error_type": None})
    evaluator = Evaluator(llm_client=llm_client)
    result = await evaluator.evaluate_freeform(_freeform_exercise(), "11/12")
    assert result == EvaluationResult(is_correct=True, error_type=None)


@pytest.mark.asyncio
async def test_freeform_incorrect_with_error_type():
    llm_client = FakeLLMClient({"is_correct": False, "error_type": "calculation"})
    evaluator = Evaluator(llm_client=llm_client)
    result = await evaluator.evaluate_freeform(_freeform_exercise(), "3/7")
    assert result == EvaluationResult(is_correct=False, error_type="calculation")


@pytest.mark.asyncio
async def test_freeform_rejects_missing_is_correct():
    llm_client = FakeLLMClient({"error_type": None})
    evaluator = Evaluator(llm_client=llm_client)
    with pytest.raises(LLMResponseError):
        await evaluator.evaluate_freeform(_freeform_exercise(), "11/12")


@pytest.mark.asyncio
async def test_freeform_rejects_invalid_error_type():
    llm_client = FakeLLMClient({"is_correct": False, "error_type": "typo"})
    evaluator = Evaluator(llm_client=llm_client)
    with pytest.raises(LLMResponseError):
        await evaluator.evaluate_freeform(_freeform_exercise(), "3/7")


@pytest.mark.asyncio
async def test_freeform_rejects_correct_with_error_type():
    llm_client = FakeLLMClient({"is_correct": True, "error_type": "calculation"})
    evaluator = Evaluator(llm_client=llm_client)
    with pytest.raises(LLMResponseError):
        await evaluator.evaluate_freeform(_freeform_exercise(), "11/12")


@pytest.mark.asyncio
async def test_freeform_rejects_overlong_answer():
    evaluator = Evaluator(llm_client=FakeLLMClient({"is_correct": True, "error_type": None}))
    with pytest.raises(ValueError):
        await evaluator.evaluate_freeform(_freeform_exercise(), "x" * 2001)


@pytest.mark.asyncio
async def test_evaluate_dispatches_by_kind():
    evaluator = Evaluator(llm_client=FakeLLMClient({"is_correct": True, "error_type": None}))
    mcq_result = await evaluator.evaluate(_mcq_exercise("B"), "B")
    freeform_result = await evaluator.evaluate(_freeform_exercise(), "11/12")
    assert mcq_result.is_correct is True
    assert freeform_result.is_correct is True
