from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.llm_client import LLMResponseError
from app.models.curriculum import Exercise
from app.tools.diagnostician import Diagnostician

MISCONCEPTION_A_ID = uuid4()
MISCONCEPTION_A_CODE = "ADDS_NUM_DENOM_DIRECTLY"
MISCONCEPTION_B_ID = uuid4()
MISCONCEPTION_B_CODE = "WRONG_LCM"


class FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    """Stub AsyncSession — returns a preset result for every .execute() call."""

    def __init__(self, result):
        self.result = result

    async def execute(self, *_args, **_kwargs):
        return self.result


class FakeLLMClient:
    def __init__(self, response: dict):
        self.response = response

    async def complete_json(self, model, system_prompt, user_prompt):
        return self.response


def _mcq_exercise() -> Exercise:
    return Exercise(
        kind="mcq",
        question="2/3 + 1/4?",
        correct_answer="B",
        options=[
            {"key": "A", "label": "2/5", "misconception_id": str(MISCONCEPTION_A_ID)},
            {"key": "B", "label": "11/12", "misconception_id": None},
            {"key": "C", "label": "3/12", "misconception_id": str(MISCONCEPTION_B_ID)},
        ],
    )


def _freeform_exercise() -> Exercise:
    return Exercise(
        kind="short_answer",
        concept_id=uuid4(),
        question="Berapa hasil dari 2/3 + 1/4?",
        correct_answer="11/12",
    )


@pytest.mark.asyncio
async def test_mcq_diagnoses_tagged_distractor():
    db = FakeSession(FakeScalarResult(MISCONCEPTION_A_CODE))
    diagnostician = Diagnostician(db=db, llm_client=None)
    code = await diagnostician.diagnose_mcq(_mcq_exercise(), "A")
    assert code == MISCONCEPTION_A_CODE


@pytest.mark.asyncio
async def test_mcq_untagged_option_returns_none():
    db = FakeSession(FakeScalarResult(None))
    diagnostician = Diagnostician(db=db, llm_client=None)
    code = await diagnostician.diagnose_mcq(_mcq_exercise(), "B")
    assert code is None


@pytest.mark.asyncio
async def test_mcq_unknown_key_returns_none():
    db = FakeSession(FakeScalarResult(None))
    diagnostician = Diagnostician(db=db, llm_client=None)
    code = await diagnostician.diagnose_mcq(_mcq_exercise(), "Z")
    assert code is None


@pytest.mark.asyncio
async def test_freeform_accepts_in_set_hypothesis():
    candidates = [
        SimpleNamespace(code=MISCONCEPTION_A_CODE, description="adds numerators/denominators directly"),
        SimpleNamespace(code=MISCONCEPTION_B_CODE, description="uses the wrong LCM"),
    ]
    db = FakeSession(FakeRowsResult(candidates))
    llm_client = FakeLLMClient({"misconception_code": MISCONCEPTION_A_CODE})
    diagnostician = Diagnostician(db=db, llm_client=llm_client)
    code = await diagnostician.diagnose_freeform(_freeform_exercise(), "2/5")
    assert code == MISCONCEPTION_A_CODE


@pytest.mark.asyncio
async def test_freeform_rejects_out_of_set_hypothesis():
    candidates = [SimpleNamespace(code=MISCONCEPTION_A_CODE, description="adds numerators/denominators directly")]
    db = FakeSession(FakeRowsResult(candidates))
    llm_client = FakeLLMClient({"misconception_code": "MADE_UP_CODE"})
    diagnostician = Diagnostician(db=db, llm_client=llm_client)
    code = await diagnostician.diagnose_freeform(_freeform_exercise(), "3/7")
    assert code is None


@pytest.mark.asyncio
async def test_freeform_accepts_null_hypothesis():
    candidates = [SimpleNamespace(code=MISCONCEPTION_A_CODE, description="adds numerators/denominators directly")]
    db = FakeSession(FakeRowsResult(candidates))
    llm_client = FakeLLMClient({"misconception_code": None})
    diagnostician = Diagnostician(db=db, llm_client=llm_client)
    code = await diagnostician.diagnose_freeform(_freeform_exercise(), "some random slip")
    assert code is None


@pytest.mark.asyncio
async def test_freeform_no_candidates_returns_none_without_llm_call():
    db = FakeSession(FakeRowsResult([]))
    diagnostician = Diagnostician(db=db, llm_client=None)
    code = await diagnostician.diagnose_freeform(_freeform_exercise(), "3/7")
    assert code is None


@pytest.mark.asyncio
async def test_freeform_rejects_malformed_llm_response():
    candidates = [SimpleNamespace(code=MISCONCEPTION_A_CODE, description="adds numerators/denominators directly")]
    db = FakeSession(FakeRowsResult(candidates))
    llm_client = FakeLLMClient({"not_the_expected_key": "oops"})
    diagnostician = Diagnostician(db=db, llm_client=llm_client)
    with pytest.raises(LLMResponseError):
        await diagnostician.diagnose_freeform(_freeform_exercise(), "3/7")


@pytest.mark.asyncio
async def test_freeform_rejects_overlong_answer():
    db = FakeSession(FakeRowsResult([]))
    diagnostician = Diagnostician(db=db, llm_client=None)
    with pytest.raises(ValueError):
        await diagnostician.diagnose_freeform(_freeform_exercise(), "x" * 2001)


@pytest.mark.asyncio
async def test_diagnose_dispatches_by_kind():
    db = FakeSession(FakeScalarResult(MISCONCEPTION_A_CODE))
    diagnostician = Diagnostician(db=db, llm_client=None)
    code = await diagnostician.diagnose(_mcq_exercise(), "A")
    assert code == MISCONCEPTION_A_CODE
