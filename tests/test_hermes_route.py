"""Route-level tests for POST /api/v1/agent/hermes.

Every other test in this suite stops at the service layer, so nothing has ever
exercised what FastAPI itself does to a request on the way in and on the way
out. This file covers the three things that live only in the route and schema:

  1. HermesAgentRequest's aliases and its model_validator. The frontend sends
     `user_id`/`prompt`, not `student_id`/`student_answer`, and exercise_id has
     to default when neither it nor problem_id is supplied. A rename in the
     schema would break the frontend with nothing failing here otherwise.
  2. _status_for()'s ValueError -> HTTP mapping. It picks 403 vs 404 by testing
     for the substring "does not belong to" in the exception message — so the
     status code silently depends on exact exception wording written elsewhere,
     in attempt_repository. That coupling deserves a test holding it in place.
  3. The SSE path's manual session handling. hermes.py opens its own session
     INSIDE the generator, because StreamingResponse returns before the
     generator body runs and a Depends(get_db)-yielded session would already be
     closed. The comment at hermes.py:33-35 explains the reasoning; this asserts
     the session is genuinely still usable when the generator runs.

No database and no LLM: async_session_factory and HermesAgentService are both
patched in the route module's namespace. Note the route does NOT use
Depends(get_db) — it calls async_session_factory() directly — so
app.dependency_overrides cannot reach it, and monkeypatch is the way in.
"""
import json
from uuid import UUID

import httpx
import pytest

from app.api.v1.routes import hermes as hermes_route
from app.api.v1.schemas.hermes import HermesAgentRequest, HermesNonStreamResponse
from app.main import create_app

STUDENT_ID = UUID("00000000-0000-0000-0000-000000000901")
EXERCISE_ID = UUID("00000000-0000-0000-0000-000000000401")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000701")
PROBLEM_ID = UUID("00000000-0000-0000-0000-000000000801")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000811")


class FakeSessionCM:
    """Stands in for async_session_factory()'s context manager.

    Tracks whether it was exited, so the SSE test can prove the session was
    still open while the generator was producing events.
    """

    def __init__(self):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return False


class FakeService:
    """Captures the request the route built, and replays a scripted outcome."""

    last_request: HermesAgentRequest | None = None
    sync_result: HermesNonStreamResponse | None = None
    sync_error: Exception | None = None
    stream_events: list[str] = []
    session_at_stream_time = None

    def __init__(self, db, llm_client):
        self.db = db
        self.llm_client = llm_client

    async def process_sync(self, request):
        FakeService.last_request = request
        if FakeService.sync_error is not None:
            raise FakeService.sync_error
        return FakeService.sync_result

    async def generate_stream(self, request):
        FakeService.last_request = request
        # Recorded from inside the generator body: this is the moment the real
        # service would touch the DB, and the moment a Depends-yielded session
        # would already have been closed.
        FakeService.session_at_stream_time = self.db
        for chunk in FakeService.stream_events:
            yield chunk


def _result(**overrides) -> HermesNonStreamResponse:
    payload = {
        "session_id": SESSION_ID,
        "problem_id": PROBLEM_ID,
        "attempt_id": ATTEMPT_ID,
        "attempt_number": 1,
        "is_correct": False,
        "error_type": "conceptual",
        "misconception_code": "ADDS_NUM_DENOM_DIRECTLY",
        "intervention": {
            "kind": "guiding_question",
            "rule_code": "FIRST_MISTAKE",
            "reason": "percobaan pertama salah",
            "visual": {
                "spec_version": "0.1",
                "intervention_kind": "guiding_question",
                "title": "Mulai dari mana?",
                "blocks": [{"type": "note", "tone": "info", "text": "Apa arti penyebut?"}],
            },
        },
        "mastery": 0.35,
        "confidence": 0.2,
        "processing_time_ms": 42,
    }
    payload.update(overrides)
    return HermesNonStreamResponse(**payload)


@pytest.fixture
def client(monkeypatch):
    """An ASGI-transport client with the route's DB and service both faked."""
    FakeService.last_request = None
    FakeService.sync_result = _result()
    FakeService.sync_error = None
    FakeService.stream_events = []
    FakeService.session_at_stream_time = None

    cm = FakeSessionCM()
    monkeypatch.setattr(hermes_route, "async_session_factory", lambda: cm)
    monkeypatch.setattr(hermes_route, "HermesAgentService", FakeService)
    monkeypatch.setattr(hermes_route, "get_llm_client", lambda: object())

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://test")
    http.session_cm = cm
    return http


async def _post(client, body):
    async with client as http:
        return await http.post("/api/v1/agent/hermes", json=body)


# --- schema aliases and defaults ---------------------------------------------


@pytest.mark.asyncio
async def test_accepts_frontend_aliases_user_id_and_prompt(client):
    # The frontend sends user_id/prompt; the pipeline speaks
    # student_id/student_answer. AliasChoices is the only thing bridging them.
    response = await _post(
        client,
        {"user_id": str(STUDENT_ID), "prompt": "B", "stream": False},
    )

    assert response.status_code == 200
    assert FakeService.last_request.student_id == STUDENT_ID
    assert FakeService.last_request.student_answer == "B"


@pytest.mark.asyncio
async def test_accepts_canonical_field_names_too(client):
    response = await _post(
        client,
        {"student_id": str(STUDENT_ID), "student_answer": "B", "stream": False},
    )

    assert response.status_code == 200
    assert FakeService.last_request.student_answer == "B"


@pytest.mark.asyncio
async def test_defaults_exercise_id_when_neither_exercise_nor_problem_given(client):
    await _post(client, {"prompt": "B", "stream": False})

    assert FakeService.last_request.exercise_id == EXERCISE_ID


@pytest.mark.asyncio
async def test_keeps_exercise_id_unset_when_problem_id_is_given(client):
    await _post(
        client,
        {"prompt": "B", "problem_id": str(PROBLEM_ID), "exercise_id": None, "stream": False},
    )

    # An explicit problem_id means the exercise is discoverable through it, so
    # the validator must not overwrite it with the demo default.
    assert FakeService.last_request.problem_id == PROBLEM_ID
    assert FakeService.last_request.exercise_id is None


@pytest.mark.asyncio
async def test_rejects_empty_student_answer(client):
    response = await _post(client, {"prompt": "", "stream": False})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rejects_unknown_mode(client):
    response = await _post(client, {"prompt": "B", "mode": "freestyle", "stream": False})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ignores_unknown_extra_fields(client):
    # extra="ignore" — a frontend sending a field the backend has not heard of
    # must not get a 422, or every frontend addition becomes a breaking change.
    response = await _post(
        client, {"prompt": "B", "stream": False, "some_future_field": "whatever"}
    )

    assert response.status_code == 200


# --- non-stream response shape ------------------------------------------------


@pytest.mark.asyncio
async def test_non_stream_returns_the_full_response_body(client):
    response = await _post(client, {"prompt": "A", "stream": False})
    body = response.json()

    assert body["attempt_id"] == str(ATTEMPT_ID)
    assert body["is_correct"] is False
    assert body["misconception_code"] == "ADDS_NUM_DENOM_DIRECTLY"
    assert body["intervention"]["kind"] == "guiding_question"
    assert body["mastery"] == 0.35


@pytest.mark.asyncio
async def test_non_stream_intervention_is_null_on_a_correct_answer(client):
    FakeService.sync_result = _result(
        is_correct=True, error_type=None, misconception_code=None, intervention=None
    )
    response = await _post(client, {"prompt": "B", "stream": False})

    # Documented invariant on the schema field: None iff the attempt was correct.
    assert response.json()["intervention"] is None


# --- _status_for mapping ------------------------------------------------------


@pytest.mark.asyncio
async def test_ownership_valueerror_maps_to_403(client):
    FakeService.sync_error = ValueError(
        f"session {SESSION_ID!r} does not belong to student {STUDENT_ID!r}"
    )
    response = await _post(client, {"prompt": "B", "stream": False})

    assert response.status_code == 403
    assert "does not belong to" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_row_valueerror_maps_to_404(client):
    FakeService.sync_error = ValueError(f"exercise {EXERCISE_ID!r} not found")
    response = await _post(client, {"prompt": "B", "stream": False})

    assert response.status_code == 404


def test_status_for_depends_on_exact_wording():
    from fastapi import status

    # This is the fragile part worth naming: the status code is decided by a
    # substring match, so rewording the exception in attempt_repository would
    # silently turn a 403 into a 404.
    assert hermes_route._status_for(ValueError("x does not belong to y")) == status.HTTP_403_FORBIDDEN
    assert hermes_route._status_for(ValueError("belongs to nobody")) == status.HTTP_404_NOT_FOUND
    assert hermes_route._status_for(ValueError("")) == status.HTTP_404_NOT_FOUND


# --- SSE path -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_sets_sse_headers(client):
    FakeService.stream_events = ["event: done\ndata: {}\n\n"]
    async with client as http:
        response = await http.post("/api/v1/agent/hermes", json={"prompt": "B", "stream": True})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    # Proxies buffer SSE by default, which stalls the stream until it completes.
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_stream_defaults_to_true_when_omitted(client):
    FakeService.stream_events = ["event: done\ndata: {}\n\n"]
    async with client as http:
        response = await http.post("/api/v1/agent/hermes", json={"prompt": "B"})

    assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_stream_passes_events_through_verbatim(client):
    FakeService.stream_events = [
        'event: thinking\ndata: {"thought": "Menilai jawaban siswa..."}\n\n',
        'event: tool_result\ndata: {"is_correct": false}\n\n',
        'event: done\ndata: {"mastery": 0.35}\n\n',
    ]
    async with client as http:
        response = await http.post("/api/v1/agent/hermes", json={"prompt": "A", "stream": True})

    text = response.text
    assert "event: thinking" in text
    assert "event: done" in text
    # SSE frames are separated by a blank line; a lost \n\n merges two events
    # into one and the browser's EventSource drops both.
    assert text.count("\n\n") == 3

    done_line = next(
        line for line in text.splitlines() if line.startswith("data:") and "mastery" in line
    )
    assert json.loads(done_line[len("data:"):])["mastery"] == 0.35


@pytest.mark.asyncio
async def test_stream_session_is_still_open_while_the_generator_runs(client):
    FakeService.stream_events = ["event: done\ndata: {}\n\n"]
    cm = client.session_cm

    async with client as http:
        await http.post("/api/v1/agent/hermes", json={"prompt": "B", "stream": True})

    # The whole reason hermes.py:36-40 opens its own session instead of taking
    # Depends(get_db): the generator body runs after StreamingResponse has
    # already returned. If the session were request-scoped it would be closed
    # by now, and this is what proves it was not.
    assert cm.entered is True
    assert FakeService.session_at_stream_time is cm
    # And it must still be closed once the response is fully consumed.
    assert cm.exited is True


@pytest.mark.asyncio
async def test_stream_and_non_stream_take_different_code_paths(client):
    FakeService.stream_events = ["event: done\ndata: {}\n\n"]
    async with client as http:
        streamed = await http.post("/api/v1/agent/hermes", json={"prompt": "B", "stream": True})
        plain = await http.post("/api/v1/agent/hermes", json={"prompt": "B", "stream": False})

    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert plain.headers["content-type"].startswith("application/json")
