import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_hermes_agent_stream():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "user_id": "123e4567-e89b-12d3-a456-426614174000",
            "prompt": "Bagaimana cara menyederhanakan aljabar 3x + 2x?",
            "mode": "ask",
            "context_window": {
                "scaffold_level": 1,
                "current_topic": "Aljabar",
            },
            "stream": True,
        }
        async with client.stream("POST", "/api/v1/agent/hermes", json=payload) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            lines = []
            async for line in resp.aiter_lines():
                if line:
                    lines.append(line)
            assert any("event: thinking" in l for l in lines)
            assert any("event: tool_call" in l for l in lines)
            assert any("event: token" in l for l in lines)
            assert any("event: done" in l for l in lines)


@pytest.mark.asyncio
async def test_hermes_agent_non_stream():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "user_id": "123e4567-e89b-12d3-a456-426614174000",
            "prompt": "Beri aku soal latihan aljabar.",
            "mode": "learning_path",
            "context_window": {
                "scaffold_level": 3,
                "current_topic": "Aljabar",
            },
            "stream": False,
        }
        resp = await client.post("/api/v1/agent/hermes", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["scaffold_level"] == 3
        assert data["mode_used"] == "learning_path"
        assert len(data["reply"]) > 0
