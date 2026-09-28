from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.llm_client import LLMResponseError
from app.models.curriculum import Exercise
from app.tools.intervention_generator import InterventionContent, InterventionGenerator
from app.tools.policy_engine import PolicyDecision


class FakeFirstResult:
    """Stub for a SQLAlchemy Result whose only use here is .first()."""

    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    """Stub AsyncSession — returns queued results in call order, one per .execute()."""

    def __init__(self, results: list):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)


class FakeLLMClient:
    def __init__(self, response: dict):
        self.response = response
        self.last_call = None

    async def complete_json(self, model, system_prompt, user_prompt):
        self.last_call = {"model": model, "system_prompt": system_prompt, "user_prompt": user_prompt}
        return self.response


def _exercise(**overrides) -> Exercise:
    defaults = dict(
        kind="short_answer",
        concept_id=uuid4(),
        question="Berapa hasil dari 1/4 + 1/6?",
        correct_answer="5/12",
        solution_steps=["KPK dari 4 dan 6 = 12", "1/4 = 3/12, 1/6 = 2/12", "3/12 + 2/12 = 5/12"],
    )
    defaults.update(overrides)
    return Exercise(**defaults)


@pytest.mark.asyncio
async def test_guiding_question():
    llm_client = FakeLLMClient({"text": "Menurutmu, apa yang harus disamakan dulu?"})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")
    result = await generator.generate(_exercise(), decision)
    assert result == InterventionContent(text="Menurutmu, apa yang harus disamakan dulu?")


@pytest.mark.asyncio
async def test_hint_without_student_answer():
    llm_client = FakeLLMClient({"text": "Coba cek KPK-nya lagi."})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")
    result = await generator.generate(_exercise(), decision)
    assert result.text == "Coba cek KPK-nya lagi."


@pytest.mark.asyncio
async def test_hint_with_student_answer_is_included_in_prompt():
    llm_client = FakeLLMClient({"text": "Coba cek KPK-nya lagi."})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")
    await generator.generate(_exercise(), decision, student_answer="2/10")
    assert "2/10" in llm_client.last_call["user_prompt"]
    assert "<<<STUDENT_ANSWER_START>>>" in llm_client.last_call["user_prompt"]


@pytest.mark.asyncio
async def test_hint_rejects_overlong_student_answer():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient({"text": "x"}))
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision, student_answer="x" * 2001)


@pytest.mark.asyncio
async def test_explanation_requires_misconception_code():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient({"text": "x"}))
    decision = PolicyDecision(kind="explanation", rule_code="MISCONCEPTION_DETECTED", reason="detected")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision, misconception_code=None)


@pytest.mark.asyncio
async def test_explanation_looks_up_misconception_and_chunk():
    misconception_row = SimpleNamespace(
        description="menjumlahkan pembilang dan penyebut langsung",
        remediation_hint="Tunjukkan mengapa penyebut harus disamakan dulu.",
    )
    chunk_row = SimpleNamespace(content="Penjumlahan pecahan butuh penyebut yang sama...")
    db = FakeSession([FakeFirstResult(misconception_row), FakeFirstResult(chunk_row)])
    llm_client = FakeLLMClient({"text": "Yuk kita bahas ulang..."})
    generator = InterventionGenerator(db=db, llm_client=llm_client)
    decision = PolicyDecision(kind="explanation", rule_code="MISCONCEPTION_DETECTED", reason="detected")

    result = await generator.generate(_exercise(), decision, misconception_code="ADDS_NUM_DENOM_DIRECTLY")

    assert result.text == "Yuk kita bahas ulang..."
    assert "menjumlahkan pembilang dan penyebut langsung" in llm_client.last_call["user_prompt"]
    assert "Penjumlahan pecahan butuh penyebut yang sama" in llm_client.last_call["user_prompt"]


@pytest.mark.asyncio
async def test_explanation_works_without_a_curriculum_chunk():
    misconception_row = SimpleNamespace(description="salah konsep", remediation_hint=None)
    db = FakeSession([FakeFirstResult(misconception_row), FakeFirstResult(None)])
    llm_client = FakeLLMClient({"text": "Penjelasan ulang..."})
    generator = InterventionGenerator(db=db, llm_client=llm_client)
    decision = PolicyDecision(kind="explanation", rule_code="REPEAT_MISCONCEPTION", reason="repeat")

    result = await generator.generate(_exercise(), decision, misconception_code="SOME_CODE")
    assert result.text == "Penjelasan ulang..."


@pytest.mark.asyncio
async def test_explanation_rejects_unknown_misconception_code():
    db = FakeSession([FakeFirstResult(None)])
    generator = InterventionGenerator(db=db, llm_client=FakeLLMClient({"text": "x"}))
    decision = PolicyDecision(kind="explanation", rule_code="MISCONCEPTION_DETECTED", reason="detected")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision, misconception_code="NOT_REAL")


@pytest.mark.asyncio
async def test_worked_example_excludes_final_step():
    llm_client = FakeLLMClient({"text": "Langkah 1... Langkah 2..."})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="worked_example", rule_code="REPEATED_MISTAKES_WORKED_EXAMPLE", reason="3 mistakes")

    result = await generator.generate(_exercise(), decision)

    assert result.text == "Langkah 1... Langkah 2..."
    prompt = llm_client.last_call["user_prompt"]
    assert "KPK dari 4 dan 6 = 12" in prompt
    assert "1/4 = 3/12, 1/6 = 2/12" in prompt
    assert "3/12 + 2/12 = 5/12" not in prompt  # final step (contains the answer) must be withheld


@pytest.mark.asyncio
async def test_worked_example_requires_solution_steps():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient({"text": "x"}))
    decision = PolicyDecision(kind="worked_example", rule_code="REPEATED_MISTAKES_WORKED_EXAMPLE", reason="3 mistakes")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(solution_steps=None), decision)


@pytest.mark.asyncio
async def test_generate_rejects_unknown_kind():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient({"text": "x"}))
    decision = PolicyDecision(kind="difficulty_up", rule_code="STREAK_MASTERY_UP", reason="streak")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision)


@pytest.mark.asyncio
async def test_rejects_malformed_llm_response():
    llm_client = FakeLLMClient({"not_text": "oops"})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")
    with pytest.raises(LLMResponseError):
        await generator.generate(_exercise(), decision)


@pytest.mark.asyncio
async def test_rejects_empty_text_response():
    llm_client = FakeLLMClient({"text": "   "})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")
    with pytest.raises(LLMResponseError):
        await generator.generate(_exercise(), decision)
