"""CurriculumRetriever picks its similarity threshold and column by embedding space."""
import pytest

from app.api.v1.services import retriever as retr


class Row:
    def __init__(self, sim):
        self.id = "00000000-0000-0000-0000-000000000501"
        self.concept_id = "00000000-0000-0000-0000-000000000601"
        self.content = "isi"
        self.metadata = {}
        self.similarity = sim


class FakeDB:
    def __init__(self, sims):
        self.sims = sims
        self.sql = ""

    async def execute(self, statement, params=None):
        self.sql = str(statement)
        sims = self.sims

        class R:
            def fetchall(_self):
                return [Row(s) for s in sims]

        return R()


class FakeRouter:
    def __init__(self, space):
        self.space = space

    async def embed(self, texts, kind="query"):
        return self.space, [[1.0, 0.0]]


def _retriever(space, sims):
    r = retr.CurriculumRetriever(FakeDB(sims), llm_client=None)
    r.router = FakeRouter(space)
    return r


@pytest.mark.asyncio
async def test_gemini_space_uses_065_and_embedding_column(monkeypatch):
    monkeypatch.setattr(retr.settings, "retrieval_threshold_gemini", 0.65)
    r = _retriever("gemini", [0.70, 0.60])
    chunks = await r.search("q")
    assert [c.similarity for c in chunks] == [0.70]
    assert "embedding <=>" in r.db.sql and "embedding_local" not in r.db.sql


@pytest.mark.asyncio
async def test_local_space_uses_lower_threshold_and_local_column(monkeypatch):
    monkeypatch.setattr(retr.settings, "retrieval_threshold_local", 0.55)
    r = _retriever("local", [0.70, 0.58, 0.50])
    chunks = await r.search("q")
    assert [c.similarity for c in chunks] == [0.70, 0.58]
    assert "embedding_local <=>" in r.db.sql


@pytest.mark.asyncio
async def test_explicit_threshold_overrides_space_default():
    r = _retriever("local", [0.70, 0.58])
    chunks = await r.search("q", threshold=0.65)
    assert [c.similarity for c in chunks] == [0.70]
