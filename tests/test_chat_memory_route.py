"""Route-level tests for GET/POST /api/v1/chat/memory.

tests/test_student_memory.py covers the service; this covers the two things the
route adds on top of it and nothing else tests:

  - the student_id default. Both endpoints fall back to DEFAULT_STUDENT_ID when
    the caller omits it, by two different mechanisms (a Query default on GET, a
    model field default on POST). They have to agree, or a client that reads
    with one and writes with the other silently touches two different rows.
  - StudentMemorySaveRequest's optionality. Every field except student_id is
    nullable, because save_memory merges rather than replaces — a partial POST
    must not be a 422, and must not blank the fields it left out.

Unlike the hermes route, these two use Depends(get_db), so the session is
replaced through app.dependency_overrides rather than monkeypatch.
"""
import pytest
import httpx
from fastapi import FastAPI

from app.api.v1.routes import chat as chat_route
from app.api.v1.services.student_memory import DEFAULT_STUDENT_ID
from app.core.config import settings
from app.core.database import get_db

STUDENT_ID = "00000000-0000-0000-0000-000000000901"


class FakeMemoryService:
    """Records what the route asked for, without touching a database."""

    get_calls: list[str] = []
    save_calls: list[dict] = []
    memory: dict = {}

    def __init__(self, db):
        self.db = db

    async def get_memory(self, student_id):
        FakeMemoryService.get_calls.append(student_id)
        return dict(FakeMemoryService.memory, student_id=student_id)

    async def save_memory(self, **kwargs):
        FakeMemoryService.save_calls.append(kwargs)
        return dict(FakeMemoryService.memory, **{k: v for k, v in kwargs.items() if v is not None})


@pytest.fixture
def client(monkeypatch):
    FakeMemoryService.get_calls = []
    FakeMemoryService.save_calls = []
    FakeMemoryService.memory = {
        "name": "Budi",
        "grade": "Kelas 7",
        "goal": None,
        "topic": None,
        "facts": [],
        "summary": None,
    }

    monkeypatch.setattr(chat_route, "StudentMemoryService", FakeMemoryService)

    # A minimal app with only this router: create_app() also mounts routes whose
    # import-time side effects are irrelevant here, and a narrower app makes a
    # failure point at this router rather than at app assembly.
    app = FastAPI()
    app.include_router(chat_route.router, prefix=settings.api_v1_prefix)
    app.dependency_overrides[get_db] = lambda: iter([object()])

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# --- GET /chat/memory ---------------------------------------------------------


@pytest.mark.asyncio
async def test_get_memory_uses_the_student_id_from_the_query(client):
    async with client as http:
        response = await http.get(f"/api/v1/chat/memory?student_id={STUDENT_ID}")

    assert response.status_code == 200
    assert FakeMemoryService.get_calls == [STUDENT_ID]
    assert response.json()["name"] == "Budi"


@pytest.mark.asyncio
async def test_get_memory_falls_back_to_the_default_student(client):
    async with client as http:
        response = await http.get("/api/v1/chat/memory")

    assert response.status_code == 200
    assert FakeMemoryService.get_calls == [DEFAULT_STUDENT_ID]


# --- POST /chat/memory --------------------------------------------------------


@pytest.mark.asyncio
async def test_save_memory_forwards_every_field(client):
    async with client as http:
        response = await http.post(
            "/api/v1/chat/memory",
            json={
                "student_id": STUDENT_ID,
                "name": "Siti",
                "grade": "Kelas 7",
                "goal": "Juara OSN",
                "topic": "pecahan",
                "facts": ["suka bola"],
                "summary": "ringkasan",
            },
        )

    assert response.status_code == 200
    call = FakeMemoryService.save_calls[0]
    assert call["student_id"] == STUDENT_ID
    assert call["name"] == "Siti"
    assert call["goal"] == "Juara OSN"
    assert call["facts"] == ["suka bola"]
    assert call["summary"] == "ringkasan"


@pytest.mark.asyncio
async def test_save_memory_accepts_a_partial_payload(client):
    # save_memory merges, so a caller updating only the goal must be able to
    # send only the goal. A required field here would force clients to re-send
    # the whole record and risk clobbering fields they never read.
    async with client as http:
        response = await http.post("/api/v1/chat/memory", json={"goal": "Lulus UTBK"})

    assert response.status_code == 200
    call = FakeMemoryService.save_calls[0]
    assert call["goal"] == "Lulus UTBK"
    assert call["name"] is None
    assert call["facts"] is None


@pytest.mark.asyncio
async def test_save_memory_defaults_to_the_same_student_as_get(client):
    async with client as http:
        await http.post("/api/v1/chat/memory", json={"name": "Budi"})

    # The two endpoints derive the default differently — a Query default on GET,
    # a field default on POST — so they are asserted to agree rather than
    # assumed to.
    assert FakeMemoryService.save_calls[0]["student_id"] == DEFAULT_STUDENT_ID


@pytest.mark.asyncio
async def test_save_memory_rejects_a_non_list_facts_value(client):
    async with client as http:
        response = await http.post(
            "/api/v1/chat/memory", json={"facts": "suka bola"}
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_save_memory_accepts_an_empty_body(client):
    async with client as http:
        response = await http.post("/api/v1/chat/memory", json={})

    assert response.status_code == 200
