from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.tools import attempt_repository as repo
from app.tools.policy_engine import AttemptRecord


class FakeResult:
    """Stub for a SQLAlchemy Result — scalar and row-iteration modes, per call site."""

    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    """Stub AsyncSession — returns queued results in call order, one per .execute()."""

    def __init__(self, results: list):
        self._results = list(results)
        self.added = []

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()


@pytest.mark.asyncio
async def test_get_exercise_found():
    exercise = SimpleNamespace(id=uuid4(), concept_id=uuid4())
    db = FakeSession([FakeResult(value=exercise)])
    assert await repo.get_exercise(db, exercise.id) is exercise


@pytest.mark.asyncio
async def test_get_exercise_not_found():
    db = FakeSession([FakeResult(value=None)])
    with pytest.raises(ValueError):
        await repo.get_exercise(db, uuid4())


@pytest.mark.asyncio
async def test_get_or_create_session_loads_existing():
    student_id = uuid4()
    session_row = SimpleNamespace(id=uuid4(), student_id=student_id)
    db = FakeSession([FakeResult(value=session_row)])
    result = await repo.get_or_create_session(db, session_row.id, student_id, "ask")
    assert result is session_row


@pytest.mark.asyncio
async def test_get_or_create_session_missing_id_raises():
    db = FakeSession([FakeResult(value=None)])
    with pytest.raises(ValueError):
        await repo.get_or_create_session(db, uuid4(), uuid4(), "ask")


@pytest.mark.asyncio
async def test_get_or_create_session_rejects_other_students_session():
    session_row = SimpleNamespace(id=uuid4(), student_id=uuid4())
    db = FakeSession([FakeResult(value=session_row)])
    with pytest.raises(ValueError):
        await repo.get_or_create_session(db, session_row.id, uuid4(), "ask")


@pytest.mark.asyncio
async def test_get_or_create_session_creates_new():
    db = FakeSession([])
    student_id = uuid4()
    result = await repo.get_or_create_session(db, None, student_id, "ask")
    assert result.student_id == student_id
    assert result.mode == "ask"
    assert result.status == "active"
    assert result.id is not None


@pytest.mark.asyncio
async def test_get_or_create_problem_loads_existing():
    problem_row = SimpleNamespace(id=uuid4(), session_id=uuid4())
    db = FakeSession([FakeResult(value=problem_row)])
    result = await repo.get_or_create_problem(db, problem_row.id, problem_row.session_id, None)
    assert result is problem_row


@pytest.mark.asyncio
async def test_get_or_create_problem_rejects_wrong_session():
    problem_row = SimpleNamespace(id=uuid4(), session_id=uuid4())
    db = FakeSession([FakeResult(value=problem_row)])
    with pytest.raises(ValueError):
        await repo.get_or_create_problem(db, problem_row.id, uuid4(), None)


@pytest.mark.asyncio
async def test_get_or_create_problem_requires_exercise_id_when_new():
    db = FakeSession([])
    with pytest.raises(ValueError):
        await repo.get_or_create_problem(db, None, uuid4(), None)


@pytest.mark.asyncio
async def test_get_or_create_problem_creates_new():
    exercise = SimpleNamespace(id=uuid4(), concept_id=uuid4())
    db = FakeSession([FakeResult(value=exercise)])
    session_id = uuid4()
    result = await repo.get_or_create_problem(db, None, session_id, exercise.id)
    assert result.session_id == session_id
    assert result.concept_id == exercise.concept_id
    assert result.exercise_id == exercise.id
    assert result.source == "exercise"


@pytest.mark.asyncio
async def test_next_attempt_number():
    db = FakeSession([FakeResult(value=2)])
    assert await repo.next_attempt_number(db, uuid4()) == 3


@pytest.mark.asyncio
async def test_load_attempt_history_maps_rows():
    rows = [
        SimpleNamespace(error_type="calculation", code=None),
        SimpleNamespace(error_type=None, code="ADDS_NUM_DENOM_DIRECTLY"),
    ]
    db = FakeSession([FakeResult(rows=rows)])
    history = await repo.load_attempt_history(db, uuid4())
    assert history == [
        AttemptRecord(error_type="calculation", misconception_code=None, is_correct=False),
        AttemptRecord(error_type=None, misconception_code="ADDS_NUM_DENOM_DIRECTLY", is_correct=False),
    ]


@pytest.mark.asyncio
async def test_has_seen_misconception_true():
    db = FakeSession([FakeResult(value={"SOME_CODE": 2})])
    assert await repo.has_seen_misconception(db, uuid4(), uuid4(), "SOME_CODE") is True


@pytest.mark.asyncio
async def test_has_seen_misconception_false_when_not_counted():
    db = FakeSession([FakeResult(value={"OTHER_CODE": 1})])
    assert await repo.has_seen_misconception(db, uuid4(), uuid4(), "SOME_CODE") is False


@pytest.mark.asyncio
async def test_has_seen_misconception_false_when_no_row():
    db = FakeSession([FakeResult(value=None)])
    assert await repo.has_seen_misconception(db, uuid4(), uuid4(), "SOME_CODE") is False


@pytest.mark.asyncio
async def test_resolve_misconception_uuid_none_code():
    db = FakeSession([])
    assert await repo.resolve_misconception_uuid(db, None) is None


@pytest.mark.asyncio
async def test_resolve_misconception_uuid_found():
    misconception_id = uuid4()
    db = FakeSession([FakeResult(value=misconception_id)])
    assert await repo.resolve_misconception_uuid(db, "SOME_CODE") == misconception_id


@pytest.mark.asyncio
async def test_resolve_misconception_uuid_unknown_code():
    db = FakeSession([FakeResult(value=None)])
    with pytest.raises(ValueError):
        await repo.resolve_misconception_uuid(db, "NOT_REAL")
