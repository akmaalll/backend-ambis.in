from uuid import uuid4
import pytest
from app.api.v1.schemas.curriculum import (
    SubjectResponse,
    UnitResponse,
    ConceptResponse,
    ExerciseResponse,
)
from app.api.v1.services.curriculum import CurriculumService
from app.models.curriculum import Subject, Unit, Concept, Exercise


class FakeResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        class _Scalars:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return _Scalars(self._rows)


class FakeSession:
    def __init__(self, results: list):
        self._results = list(results)

    async def execute(self, *_args, **_kwargs):
        if not self._results:
            return FakeResult(None, [])
        return self._results.pop(0)


def test_subject_response_schema():
    sub_id = uuid4()
    resp = SubjectResponse(id=sub_id, code="MTK", name="Matematika")
    assert resp.id == sub_id
    assert resp.code == "MTK"
    assert resp.name == "Matematika"


def test_unit_response_schema():
    unit_id = uuid4()
    sub_id = uuid4()
    resp = UnitResponse(id=unit_id, subject_id=sub_id, name="Bilangan Pecahan", position=1)
    assert resp.id == unit_id
    assert resp.position == 1


def test_concept_response_schema():
    concept_id = uuid4()
    unit_id = uuid4()
    resp = ConceptResponse(
        id=concept_id,
        unit_id=unit_id,
        code="MTK.PECAHAN.SENILAI",
        name="Pecahan Senilai",
        description="Deskripsi konsep",
        position=1,
    )
    assert resp.code == "MTK.PECAHAN.SENILAI"
    assert resp.description == "Deskripsi konsep"


def test_exercise_response_schema():
    ex_id = uuid4()
    concept_id = uuid4()
    resp = ExerciseResponse(
        id=ex_id,
        concept_id=concept_id,
        difficulty=2,
        kind="mcq",
        is_diagnostic=True,
        question="1/2 + 1/3 = ?",
        options=[{"key": "A", "label": "5/6"}],
        correct_answer="A",
        metadata={"source": "seed"},
    )
    assert resp.difficulty == 2
    assert resp.is_diagnostic is True
    assert resp.metadata == {"source": "seed"}
    # Verify serialization alias in model_dump
    dumped = resp.model_dump(by_alias=True)
    assert "metadata" in dumped
    assert dumped["metadata"]["source"] == "seed"


@pytest.mark.asyncio
async def test_curriculum_service_list_subjects():
    sub = Subject(id=uuid4(), code="MTK", name="Matematika")
    session = FakeSession([FakeResult(rows=[sub])])
    service = CurriculumService(session)

    subjects = await service.list_subjects()
    assert len(subjects) == 1
    assert subjects[0].code == "MTK"


@pytest.mark.asyncio
async def test_curriculum_service_get_concept():
    cid = uuid4()
    concept = Concept(id=cid, unit_id=uuid4(), code="TEST", name="Test Concept", position=1)
    session = FakeSession([FakeResult(value=concept)])
    service = CurriculumService(session)

    found = await service.get_concept(cid)
    assert found is not None
    assert found.code == "TEST"
