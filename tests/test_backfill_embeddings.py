import re

import pytest

from scripts import backfill_embeddings as backfill

# Same guard as test_student_memory.py: sa.text() consumes `:param`, so a
# `:param::type` cast leaves a lone `:` for Postgres to choke on. This script
# talks to the vector column through raw SQL, so it is exposed to the same trap.
BAD_CAST = re.compile(r":[A-Za-z_][A-Za-z0-9_]*::")

CHUNK_A = "00000000-0000-0000-0000-000000000501"
CHUNK_B = "00000000-0000-0000-0000-000000000502"


class FakeRow:
    def __init__(self, id, content):
        self.id = id
        self.content = content


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, select_rows):
        self._select_rows = select_rows
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.committed = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params or {})
        if sql.lstrip().upper().startswith("SELECT"):
            return FakeResult(self._select_rows)
        return FakeResult([])

    async def commit(self):
        self.committed += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeLLMClient:
    """Returns a distinct, recognisable vector per input so pairing can be checked."""

    def __init__(self, dims=768):
        self.dims = dims
        self.embed_calls: list[dict] = []
        self.closed = 0

    async def embed(self, texts, model, dimensions=None):
        self.embed_calls.append(
            {"texts": list(texts), "model": model, "dimensions": dimensions}
        )
        width = dimensions or self.dims
        # vector i is [i+1, 0, 0, ...] — the leading value identifies which text
        # it came from, which is what lets the pairing assertions bite.
        return [[float(i + 1)] + [0.0] * (width - 1) for i in range(len(texts))]

    async def aclose(self):
        self.closed += 1


@pytest.fixture
def wired(monkeypatch):
    """Point the script at fakes; return a factory the test configures."""

    def _wire(select_rows, base_url="https://router.example/v1"):
        session = FakeSession(select_rows)
        client = FakeLLMClient()

        monkeypatch.setattr(backfill.settings, "llm_base_url", base_url)
        monkeypatch.setattr(backfill.settings, "llm_api_key", "test-key")
        monkeypatch.setattr(backfill.settings, "embedding_model", "gemini-embedding-001")
        monkeypatch.setattr(backfill.settings, "embedding_dimensions", 768)
        monkeypatch.setattr(backfill, "async_session_factory", lambda: session)
        monkeypatch.setattr(backfill, "LLMClient", lambda **kwargs: client)

        return session, client

    return _wire


# --- guard rails --------------------------------------------------------------


def test_update_sql_has_no_adjacent_bind_cast():
    assert not BAD_CAST.search(backfill._UPDATE_SQL), backfill._UPDATE_SQL
    assert not BAD_CAST.search(backfill._SELECT_SQL), backfill._SELECT_SQL


def test_select_only_targets_rows_missing_an_embedding():
    # The whole script is idempotent only because of this predicate — an
    # already-embedded chunk must never be re-sent to the paid embed endpoint.
    assert "WHERE embedding IS NULL" in backfill._SELECT_SQL


def test_update_clears_the_needs_embedding_flag():
    assert "metadata - 'needs_embedding'" in backfill._UPDATE_SQL


def test_pgvector_literal_format():
    assert backfill._to_pgvector_literal([1.0, 0.5, -0.25]) == "[1.0,0.5,-0.25]"


# --- behaviour ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_entirely_when_llm_base_url_is_unset(wired):
    session, client = wired([FakeRow(CHUNK_A, "isi chunk")], base_url="")
    await backfill.backfill()

    # No DB round trip and no client construction: the guard fires first.
    assert session.statements == []
    assert client.embed_calls == []


@pytest.mark.asyncio
async def test_does_nothing_when_no_rows_need_an_embedding(wired):
    session, client = wired([])
    await backfill.backfill()

    assert len(session.statements) == 1  # the SELECT, nothing else
    assert client.embed_calls == []
    assert session.committed == 0


@pytest.mark.asyncio
async def test_embeds_every_pending_chunk_in_one_call(wired):
    rows = [FakeRow(CHUNK_A, "isi chunk A"), FakeRow(CHUNK_B, "isi chunk B")]
    session, client = wired(rows)
    await backfill.backfill()

    assert len(client.embed_calls) == 1
    call = client.embed_calls[0]
    assert call["texts"] == ["isi chunk A", "isi chunk B"]
    assert call["model"] == "gemini-embedding-001"
    assert call["dimensions"] == 768


@pytest.mark.asyncio
async def test_pairs_each_vector_with_its_own_chunk_id(wired):
    rows = [FakeRow(CHUNK_A, "isi chunk A"), FakeRow(CHUNK_B, "isi chunk B")]
    session, client = wired(rows)
    await backfill.backfill()

    updates = [p for sql, p in zip(session.statements, session.params) if "UPDATE" in sql]
    assert len(updates) == 2
    # FakeLLMClient stamps the first component with the input's index, so a
    # scrambled zip() would show up here as a swapped leading value.
    assert updates[0]["id"] == CHUNK_A
    assert updates[0]["embedding"].startswith("[1.0,")
    assert updates[1]["id"] == CHUNK_B
    assert updates[1]["embedding"].startswith("[2.0,")


@pytest.mark.asyncio
async def test_stores_full_width_vectors(wired):
    session, client = wired([FakeRow(CHUNK_A, "isi chunk A")])
    await backfill.backfill()

    literal = next(
        p["embedding"] for sql, p in zip(session.statements, session.params) if "UPDATE" in sql
    )
    assert literal.startswith("[") and literal.endswith("]")
    assert len(literal[1:-1].split(",")) == 768


@pytest.mark.asyncio
async def test_commits_once_after_all_updates(wired):
    rows = [FakeRow(CHUNK_A, "a"), FakeRow(CHUNK_B, "b")]
    session, _ = wired(rows)
    await backfill.backfill()

    assert session.committed == 1


@pytest.mark.asyncio
async def test_closes_the_llm_client_even_when_the_write_fails(wired, monkeypatch):
    session, client = wired([FakeRow(CHUNK_A, "a")])

    async def boom(statement, params=None):
        raise RuntimeError("update exploded")

    monkeypatch.setattr(session, "execute", boom)

    with pytest.raises(RuntimeError):
        await backfill.backfill()

    # aclose() lives in a finally — a leaked httpx client would warn at
    # interpreter shutdown and hold the connection pool open.
    assert client.closed == 1


@pytest.mark.asyncio
async def test_closes_the_llm_client_on_the_happy_path(wired):
    _, client = wired([FakeRow(CHUNK_A, "a")])
    await backfill.backfill()

    assert client.closed == 1


# --- local space -------------------------------------------------------------


def test_local_sql_targets_embedding_local_only():
    assert "WHERE embedding_local IS NULL" in backfill._LOCAL_SELECT_SQL
    assert "SET embedding_local =" in backfill._LOCAL_UPDATE_SQL
    assert not BAD_CAST.search(backfill._LOCAL_UPDATE_SQL)


@pytest.mark.asyncio
async def test_local_backfill_skips_without_url(wired, monkeypatch):
    session, client = wired([FakeRow(CHUNK_A, "a")])
    monkeypatch.setattr(backfill.settings, "embedding_local_url", "")
    await backfill.backfill_local()
    assert session.statements == [] and client.embed_calls == []


@pytest.mark.asyncio
async def test_local_backfill_sends_documents_and_pairs_ids(wired, monkeypatch):
    rows = [FakeRow(CHUNK_A, "a"), FakeRow(CHUNK_B, "b")]
    session, client = wired(rows)
    monkeypatch.setattr(backfill.settings, "embedding_local_url", "http://127.0.0.1:8002/v1")
    monkeypatch.setattr(backfill.settings, "embedding_local_model", "local-model")

    async def embed(texts, model, dimensions=None, extra=None):
        client.embed_calls.append({"texts": list(texts), "model": model, "extra": extra})
        return [[float(i + 1)] + [0.0] * 767 for i in range(len(texts))]

    monkeypatch.setattr(client, "embed", embed)
    await backfill.backfill_local()

    assert client.embed_calls[0]["model"] == "local-model"
    assert client.embed_calls[0]["extra"] == {"task": "document"}
    updates = [p for sql, p in zip(session.statements, session.params) if "UPDATE" in sql]
    assert [u["id"] for u in updates] == [CHUNK_A, CHUNK_B]
    assert all("embedding_local" in sql for sql in session.statements if "UPDATE" in sql)
    assert client.closed == 1
