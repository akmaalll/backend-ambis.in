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
    """Returns queued responses in call order; the last one repeats if the queue runs dry."""

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.calls: list[dict] = []

    @property
    def last_call(self):
        return self.calls[-1]

    async def complete_json(self, model, system_prompt, user_prompt):
        self.calls.append({"model": model, "system_prompt": system_prompt, "user_prompt": user_prompt})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


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


def _guiding_question_response() -> dict:
    return {
        "title": "Mulai dari mana?",
        "blocks": [
            {"type": "note", "text": "Menurutmu, apa yang harus disamakan dulu?"},
            {"type": "fraction_bar", "rows": [
                {"label": "1/4", "numerator": 1, "denominator": 4},
                {"label": "1/6", "numerator": 1, "denominator": 6},
            ]},
        ],
    }


def _hint_response() -> dict:
    return {
        "title": "Cek penyebutnya",
        "blocks": [
            {"type": "note", "text": "Coba cek KPK-nya lagi."},
            {"type": "number_line", "start": "0", "end": "1", "ticks": 12,
             "points": [{"at": "1/4", "label": "1/4"}]},
        ],
    }


def _explanation_response() -> dict:
    return {
        "title": "Kenapa penyebut harus sama",
        "blocks": [
            {"type": "analogy_scene", "template": "pizza",
             "story": "Potongan pizza beda ukuran tidak bisa langsung digabung.",
             "items": [{"fraction": "1/2"}, {"fraction": "1/3"}]},
            {"type": "step_flow", "steps": [
                {"n": 1, "title": "Samakan ukuran potongan", "math": "1/2 = 3/6 ; 1/3 = 2/6"},
                {"n": 2, "title": "Baru gabungkan", "math": "3/6 + 2/6 = 5/6"},
            ]},
            {"type": "note", "text": "Sekarang coba soalmu lagi ya."},
        ],
    }


def _worked_example_response() -> dict:
    return {
        "title": "Langkah demi langkah",
        "blocks": [
            {"type": "step_flow", "steps": [
                {"n": 1, "title": "Cari KPK", "detail": "KPK 4 dan 6 adalah 12", "math": "4 x 3 = 12"},
                {"n": 2, "title": "Ubah pecahannya", "math": "1/4 = 3/12 ; 1/6 = 2/12"},
                {"n": 3, "title": "Jumlahkan sendiri", "math": "3/12 + 2/12 = ?/12", "locked": True},
            ]},
        ],
    }


@pytest.mark.asyncio
async def test_guiding_question_returns_a_visual_spec():
    llm_client = FakeLLMClient(_guiding_question_response())
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")

    result = await generator.generate(_exercise(), decision)

    assert isinstance(result, InterventionContent)
    assert result.visual.intervention_kind == "guiding_question"
    assert result.visual.blocks[0].text == "Menurutmu, apa yang harus disamakan dulu?"
    assert len(llm_client.calls) == 1


@pytest.mark.asyncio
async def test_kind_and_version_are_set_by_code_not_trusted_from_the_llm():
    response = {**_guiding_question_response(), "intervention_kind": "worked_example", "spec_version": "9.9"}
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(response))
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")

    result = await generator.generate(_exercise(), decision)

    assert result.visual.intervention_kind == "guiding_question"
    assert result.visual.spec_version == "0.1"


@pytest.mark.asyncio
async def test_prompt_lists_only_the_blocks_allowed_for_the_kind():
    llm_client = FakeLLMClient(_hint_response())
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")

    await generator.generate(_exercise(), decision)

    prompt = llm_client.last_call["user_prompt"]
    assert "fraction_bar, note, number_line" in prompt
    assert "- step_flow" not in prompt
    assert "OUTPUT FORMAT" in prompt


@pytest.mark.asyncio
async def test_hint_without_student_answer():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(_hint_response()))
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")
    result = await generator.generate(_exercise(), decision)
    assert result.visual.blocks[0].text == "Coba cek KPK-nya lagi."


@pytest.mark.asyncio
async def test_hint_with_student_answer_is_included_in_prompt():
    llm_client = FakeLLMClient(_hint_response())
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")
    await generator.generate(_exercise(), decision, student_answer="2/10")
    assert "2/10" in llm_client.last_call["user_prompt"]
    assert "<<<STUDENT_ANSWER_START>>>" in llm_client.last_call["user_prompt"]


@pytest.mark.asyncio
async def test_hint_rejects_overlong_student_answer():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(_hint_response()))
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision, student_answer="x" * 2001)


@pytest.mark.asyncio
async def test_explanation_requires_misconception_code():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(_explanation_response()))
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
    llm_client = FakeLLMClient(_explanation_response())
    generator = InterventionGenerator(db=db, llm_client=llm_client)
    decision = PolicyDecision(kind="explanation", rule_code="MISCONCEPTION_DETECTED", reason="detected")

    result = await generator.generate(_exercise(), decision, misconception_code="ADDS_NUM_DENOM_DIRECTLY")

    assert [b.type for b in result.visual.blocks] == ["analogy_scene", "step_flow", "note"]
    assert "menjumlahkan pembilang dan penyebut langsung" in llm_client.last_call["user_prompt"]
    assert "Penjumlahan pecahan butuh penyebut yang sama" in llm_client.last_call["user_prompt"]


@pytest.mark.asyncio
async def test_explanation_works_without_a_curriculum_chunk():
    misconception_row = SimpleNamespace(description="salah konsep", remediation_hint=None)
    db = FakeSession([FakeFirstResult(misconception_row), FakeFirstResult(None)])
    generator = InterventionGenerator(db=db, llm_client=FakeLLMClient(_explanation_response()))
    decision = PolicyDecision(kind="explanation", rule_code="REPEAT_MISCONCEPTION", reason="repeat")

    result = await generator.generate(_exercise(), decision, misconception_code="SOME_CODE")
    assert result.visual.intervention_kind == "explanation"


@pytest.mark.asyncio
async def test_explanation_rejects_unknown_misconception_code():
    db = FakeSession([FakeFirstResult(None)])
    generator = InterventionGenerator(db=db, llm_client=FakeLLMClient(_explanation_response()))
    decision = PolicyDecision(kind="explanation", rule_code="MISCONCEPTION_DETECTED", reason="detected")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision, misconception_code="NOT_REAL")


@pytest.mark.asyncio
async def test_worked_example_excludes_final_step_from_the_prompt():
    llm_client = FakeLLMClient(_worked_example_response())
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="worked_example", rule_code="REPEATED_MISTAKES_WORKED_EXAMPLE", reason="3 mistakes")

    result = await generator.generate(_exercise(), decision)

    assert result.visual.blocks[0].steps[-1].locked is True
    prompt = llm_client.last_call["user_prompt"]
    assert "KPK dari 4 dan 6 = 12" in prompt
    assert "1/4 = 3/12, 1/6 = 2/12" in prompt
    assert "3/12 + 2/12 = 5/12" not in prompt  # final step (contains the answer) must be withheld


@pytest.mark.asyncio
async def test_worked_example_requires_solution_steps():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(_worked_example_response()))
    decision = PolicyDecision(kind="worked_example", rule_code="REPEATED_MISTAKES_WORKED_EXAMPLE", reason="3 mistakes")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(solution_steps=None), decision)


@pytest.mark.asyncio
async def test_generate_rejects_unknown_kind():
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(_hint_response()))
    decision = PolicyDecision(kind="difficulty_up", rule_code="STREAK_MASTERY_UP", reason="streak")
    with pytest.raises(ValueError):
        await generator.generate(_exercise(), decision)


@pytest.mark.asyncio
async def test_invalid_spec_is_retried_once_with_the_rejection_reason():
    llm_client = FakeLLMClient({"title": "x", "blocks": []}, _guiding_question_response())
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")

    result = await generator.generate(_exercise(), decision)

    assert len(llm_client.calls) == 2
    assert "Your previous JSON was rejected" in llm_client.calls[1]["user_prompt"]
    assert result.visual.title == "Mulai dari mana?"


@pytest.mark.asyncio
async def test_spec_that_stays_invalid_raises_llm_response_error():
    llm_client = FakeLLMClient({"title": "x", "blocks": []})
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="guiding_question", rule_code="INITIAL_PROMPT", reason="first attempt")

    with pytest.raises(LLMResponseError):
        await generator.generate(_exercise(), decision)
    assert len(llm_client.calls) == 2


@pytest.mark.asyncio
async def test_leaked_final_answer_is_rejected_then_retried():
    leaking = _hint_response()
    leaking["blocks"][0]["text"] = "Hasilnya 5/12, coba cek lagi."
    llm_client = FakeLLMClient(leaking, _hint_response())
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm_client)
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")

    result = await generator.generate(_exercise(), decision)

    assert "final answer" in llm_client.calls[1]["user_prompt"]
    assert "5/12" not in str(result.visual.to_payload())


@pytest.mark.asyncio
async def test_leaked_final_answer_that_persists_raises():
    leaking = _hint_response()
    leaking["blocks"][0]["text"] = "Hasilnya 10/24."
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(leaking))
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")

    with pytest.raises(LLMResponseError):
        await generator.generate(_exercise(), decision)


@pytest.mark.asyncio
async def test_block_type_not_allowed_for_the_kind_is_rejected():
    response = {**_hint_response(), "blocks": _worked_example_response()["blocks"]}
    generator = InterventionGenerator(db=FakeSession([]), llm_client=FakeLLMClient(response))
    decision = PolicyDecision(kind="hint", rule_code="FIRST_MISTAKE_HINT", reason="first mistake")

    with pytest.raises(LLMResponseError):
        await generator.generate(_exercise(), decision)
