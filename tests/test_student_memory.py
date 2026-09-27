import json
import re

import pytest

from app.api.v1.services.student_memory import (
    DEFAULT_STUDENT_ID,
    StudentMemoryService,
)

STUDENT_ID = "00000000-0000-0000-0000-000000000901"

# The defect that shipped to main: `:param::type` — sa.text() eats `:param`,
# leaving a lone `:` that Postgres rejects with a syntax error. Every raw query
# in this service must use CAST(:param AS type) instead.
BAD_CAST = re.compile(r":[A-Za-z_][A-Za-z0-9_]*::")


class FakeMappings:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return FakeMappings(self._row)


class FakeSession:
    """Records every statement it is asked to run so tests can assert on the SQL."""

    def __init__(self, results: list | None = None):
        self._results = list(results or [])
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params or {})
        if not self._results:
            return FakeResult(None)
        nxt = self._results.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


def _memory_row(**overrides):
    row = {
        "student_id": STUDENT_ID,
        "name": "Budi",
        "grade": "Kelas 7",
        "goal": "Lulus UTBK",
        "topic": "pecahan",
        "facts": ["suka bola"],
        "summary": None,
        "updated_at": "2026-09-27 10:00:00+00",
    }
    row.update(overrides)
    return row


# --- regression guard for the cast bug ---------------------------------------


@pytest.mark.asyncio
async def test_get_memory_sql_has_no_adjacent_bind_cast():
    session = FakeSession([FakeResult(None), FakeResult(None)])
    await StudentMemoryService(session).get_memory(STUDENT_ID)

    assert session.statements
    for sql in session.statements:
        assert not BAD_CAST.search(sql), sql


@pytest.mark.asyncio
async def test_save_memory_sql_has_no_adjacent_bind_cast():
    session = FakeSession([FakeResult(None), FakeResult(None)])
    await StudentMemoryService(session).save_memory(STUDENT_ID, name="Budi")

    assert session.statements
    for sql in session.statements:
        assert not BAD_CAST.search(sql), sql


# --- get_memory tiers --------------------------------------------------------


@pytest.mark.asyncio
async def test_get_memory_returns_row_from_student_memories():
    session = FakeSession([FakeResult(_memory_row())])
    mem = await StudentMemoryService(session).get_memory(STUDENT_ID)

    assert mem["name"] == "Budi"
    assert mem["grade"] == "Kelas 7"
    assert mem["facts"] == ["suka bola"]
    # Tier 1 hit must short-circuit — no profiles lookup.
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_get_memory_parses_facts_stored_as_json_string():
    session = FakeSession([FakeResult(_memory_row(facts=json.dumps(["a", "b"])))])
    mem = await StudentMemoryService(session).get_memory(STUDENT_ID)

    assert mem["facts"] == ["a", "b"]


@pytest.mark.asyncio
async def test_get_memory_drops_invalid_stored_name():
    session = FakeSession([FakeResult(_memory_row(name="siapa"))])
    mem = await StudentMemoryService(session).get_memory(STUDENT_ID)

    assert mem["name"] is None


@pytest.mark.asyncio
async def test_get_memory_falls_back_to_profiles():
    profile_row = {"id": STUDENT_ID, "display_name": "Siti", "grade": 7}
    session = FakeSession([FakeResult(None), FakeResult(profile_row)])
    mem = await StudentMemoryService(session).get_memory(STUDENT_ID)

    assert mem["name"] == "Siti"
    assert mem["grade"] == "Kelas 7"
    assert mem["goal"] is None
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_get_memory_returns_empty_shape_when_both_tiers_miss():
    session = FakeSession([RuntimeError("relation missing"), FakeResult(None)])
    mem = await StudentMemoryService(session).get_memory(STUDENT_ID)

    assert mem["student_id"] == STUDENT_ID
    assert mem["name"] is None
    assert mem["facts"] == []


# --- save_memory -------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_memory_keeps_existing_name_when_none_passed():
    session = FakeSession([FakeResult(_memory_row()), FakeResult(None), FakeResult(None)])
    saved = await StudentMemoryService(session).save_memory(STUDENT_ID, goal="Juara OSN")

    assert saved["name"] == "Budi"
    assert saved["goal"] == "Juara OSN"
    assert session.committed == 1


@pytest.mark.asyncio
async def test_save_memory_merges_and_dedupes_facts():
    session = FakeSession([FakeResult(_memory_row()), FakeResult(None), FakeResult(None)])
    saved = await StudentMemoryService(session).save_memory(
        STUDENT_ID, facts=["suka bola", "suka gambar"]
    )

    assert saved["facts"] == ["suka bola", "suka gambar"]


@pytest.mark.asyncio
async def test_save_memory_skips_question_shaped_facts():
    session = FakeSession([FakeResult(None), FakeResult(None), FakeResult(None)])
    saved = await StudentMemoryService(session).save_memory(
        STUDENT_ID, facts=["siapa namaku", "hobi basket"]
    )

    assert saved["facts"] == ["hobi basket"]


@pytest.mark.asyncio
async def test_save_memory_sends_facts_as_json_string():
    session = FakeSession([FakeResult(None), FakeResult(None), FakeResult(None)])
    await StudentMemoryService(session).save_memory(STUDENT_ID, facts=["hobi basket"])

    upsert_params = next(
        p for sql, p in zip(session.statements, session.params) if "INSERT INTO" in sql
    )
    assert json.loads(upsert_params["facts"]) == ["hobi basket"]


@pytest.mark.asyncio
async def test_save_memory_rolls_back_on_failure():
    session = FakeSession(
        [FakeResult(None), FakeResult(None), RuntimeError("upsert exploded")]
    )
    saved = await StudentMemoryService(session).save_memory(STUDENT_ID, name="Budi")

    assert session.rolled_back == 1
    assert session.committed == 0
    # The caller still gets the merged view even though the write failed.
    assert saved["name"] == "Budi"


# --- _safe_uuid --------------------------------------------------------------


def test_safe_uuid_passes_through_valid_uuid():
    assert StudentMemoryService._safe_uuid(STUDENT_ID) == STUDENT_ID


def test_safe_uuid_falls_back_on_garbage():
    assert StudentMemoryService._safe_uuid("not-a-uuid") == DEFAULT_STUDENT_ID
    assert StudentMemoryService._safe_uuid(None) == DEFAULT_STUDENT_ID
    assert StudentMemoryService._safe_uuid("") == DEFAULT_STUDENT_ID


# --- identity extraction -----------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Halo kak, nama aku Budi", "Budi"),
        ("namaku Siti Aminah", "Siti Aminah"),
        ("nama saya Reno", "Reno"),
        ("panggil aku Daffa", "Daffa"),
        ("aku Rian, siswa kelas 7", "Rian"),
    ],
)
def test_extract_identity_detects_name(message, expected):
    assert StudentMemoryService.extract_identity_from_text(message).get("name") == expected


def test_extract_identity_detects_grade():
    result = StudentMemoryService.extract_identity_from_text("nama aku Budi, kelas 7")
    assert result["name"] == "Budi"
    assert result["grade"] == "Kelas 7"


@pytest.mark.parametrize(
    "message",
    [
        "namaku siapa?",
        "siapa namaku",
        "kamu masih ingat namaku",
        "coba tebak nama aku",
    ],
)
def test_extract_identity_ignores_questions(message):
    assert StudentMemoryService.extract_identity_from_text(message) == {}


def test_is_question_about_name():
    assert StudentMemoryService.is_question_about_name("nama aku siapa?") is True
    assert StudentMemoryService.is_question_about_name("siapa aku") is True
    assert StudentMemoryService.is_question_about_name("nama aku Budi") is False


# --- name validation ---------------------------------------------------------


@pytest.mark.parametrize("name", ["Budi", "Siti Aminah", "Reno"])
def test_is_valid_name_accepts_real_names(name):
    assert StudentMemoryService._is_valid_name(name) is True


@pytest.mark.parametrize(
    "name",
    ["siapa", "aku", "kak", "siswa demo", "undefined", "", None, "a", "siapa namaku"],
)
def test_is_valid_name_rejects_non_names(name):
    assert StudentMemoryService._is_valid_name(name) is False


def test_sanitize_name_strips_filler_and_capitalizes():
    assert StudentMemoryService._sanitize_name("budi ya") == "Budi"
    assert StudentMemoryService._sanitize_name("siti aminah,") == "Siti Aminah"


def test_sanitize_name_rejects_question_strings():
    assert StudentMemoryService._sanitize_name("siapa namaku") is None
    assert StudentMemoryService._sanitize_name("kak") is None
