"""Runs the REAL LLMClient + generators against scripts/fake_llm_server over real HTTP.

Guards against drift: if a prompt template is reworded so the stub's markers stop matching,
these fail instead of the stub silently answering `{}` during a manual local run.
"""
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio

from app.api.v1.services.visual_ask import VisualAskService
from app.core.llm_client import LLMClient
from app.core.prompts import render_prompt
from app.models.curriculum import Exercise
from app.tools.evaluator import Evaluator
from app.tools.intervention_generator import InterventionGenerator
from app.tools.policy_engine import PolicyDecision
from scripts.fake_llm_server import _embedding, make_server


@pytest.fixture(scope="module")
def base_url():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest_asyncio.fixture
async def llm(base_url):
    client = LLMClient(base_url=base_url, api_key="anything")
    yield client
    await client.aclose()


class FakeFirstResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)


def _exercise() -> Exercise:
    return Exercise(
        kind="short_answer",
        concept_id=uuid4(),
        question="Ibu punya 3/5 kg gula dan menambah 1/4 kg lagi. Berapa total gula Ibu sekarang?",
        correct_answer="17/20",
        solution_steps=["KPK dari 5 dan 4 = 20", "3/5 = 12/20, 1/4 = 5/20", "12/20 + 5/20 = 17/20"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,rule",
    [
        ("guiding_question", "INITIAL_PROMPT"),
        ("hint", "FIRST_MISTAKE_HINT"),
        ("worked_example", "REPEATED_MISTAKES_WORKED_EXAMPLE"),
    ],
)
async def test_every_intervention_kind_gets_a_valid_canvas(llm, kind, rule):
    generator = InterventionGenerator(db=FakeSession([]), llm_client=llm)
    decision = PolicyDecision(kind=kind, rule_code=rule, reason="test")

    result = await generator.generate(_exercise(), decision)

    assert result.visual.intervention_kind == kind
    assert "17/20" not in str(result.visual.to_payload())


@pytest.mark.asyncio
async def test_explanation_gets_a_valid_canvas(llm):
    db = FakeSession([
        FakeFirstResult(SimpleNamespace(description="menjumlah pembilang dan penyebut", remediation_hint=None)),
        FakeFirstResult(None),
    ])
    generator = InterventionGenerator(db=db, llm_client=llm)
    decision = PolicyDecision(kind="explanation", rule_code="MISCONCEPTION_DETECTED", reason="test")

    result = await generator.generate(_exercise(), decision, misconception_code="ADDS_NUM_DENOM_DIRECTLY")

    assert [b.type for b in result.visual.blocks] == ["analogy_scene", "step_flow", "note"]


@pytest.mark.asyncio
async def test_free_question_gets_a_valid_canvas(llm):
    class NoRetrieval:
        async def search(self, query, top_k=2, threshold=0.65):
            return []

    result = await VisualAskService(db=None, llm_client=llm, retriever=NoRetrieval()).process("1/2 + 1/3 berapa?")

    assert result.visual.blocks[0].type == "step_flow"


@pytest.mark.asyncio
async def test_grading_is_real_for_equivalent_fractions(llm):
    evaluator = Evaluator(llm)
    exercise = _exercise()

    right = await evaluator.evaluate(exercise, "34/40")
    wrong = await evaluator.evaluate(exercise, "4/9")

    assert right.is_correct is True
    assert wrong.is_correct is False and wrong.error_type == "conceptual"


@pytest.mark.asyncio
async def test_embeddings_have_the_requested_dimension_and_unit_norm(llm):
    vectors = await llm.embed(["pecahan", "KPK"], model="fake", dimensions=768)

    assert [len(v) for v in vectors] == [768, 768]
    assert abs(sum(x * x for x in vectors[0]) - 1.0) < 1e-6
    assert vectors[0] != vectors[1]
    assert vectors[0] == pytest.approx(_embedding("pecahan", 768))


def test_every_prompt_template_the_stub_relies_on_still_contains_its_marker():
    from scripts.fake_llm_server import KIND_MARKERS

    rendered = {
        "ask_visual": render_prompt("ask_visual", question="q", references=[], allowed=["note"], allow_answer=True),
        "guiding_question": render_prompt("intervention_guiding_question", question="q", allowed=["note"]),
        "worked_example": render_prompt("intervention_worked_example", question="q", steps_except_last=["s"], allowed=["note"]),
        "explanation": render_prompt(
            "intervention_explanation", question="q", misconception_description="d",
            remediation_hint=None, concept_reference=None, allowed=["note"],
        ),
        "hint": render_prompt("intervention_hint", question="q", solution_steps=["s"], student_answer=None, allowed=["note"]),
    }
    for marker, kind in KIND_MARKERS:
        assert marker in rendered[kind], f"{kind} template no longer contains {marker!r}"
    assert "You are grading a middle-school" in render_prompt(
        "grading_rubric", question="q", correct_answer="a", solution_steps=None, student_answer="x"
    )
    assert "You are diagnosing WHY" in render_prompt(
        "misconception_hypothesis", question="q", student_answer="x", candidate_misconceptions=[]
    )
