import pytest
from unittest.mock import AsyncMock

from app.api.v1.schemas.learning_path import (
    GenerateRoadmapRequest,
    LessonIntroRequest,
)
from app.api.v1.services.learning_path import LearningPathService


class FakeLLMClient:
    def __init__(self, should_fail: bool = False, response_payload: dict | None = None):
        self.should_fail = should_fail
        self.response_payload = response_payload or {}

    async def complete_json(self, model: str, system_prompt: str, user_prompt: str) -> dict:
        if self.should_fail:
            raise RuntimeError("Simulated 9Router LLM failure")
        return self.response_payload


@pytest.mark.asyncio
async def test_generate_roadmap_success():
    mock_payload = {
        "title": "Roadmap Khusus Pecahan",
        "reasoning": "Disesuaikan dengan miskonsepsi siswa.",
        "steps": [
            {
                "id": "step-1",
                "title": "Pecahan Senilai",
                "description": "Visualisasi kue",
                "type": "lesson",
                "recommended_badge": "🎯 Rekomendasi Khusus Fondasi",
                "has_quiz": False,
            },
            {
                "id": "step-2",
                "title": "Latihan Pecahan",
                "description": "Latihan soal interaktif",
                "type": "practice",
                "recommended_badge": None,
                "has_quiz": True,
            },
        ],
    }
    llm = FakeLLMClient(should_fail=False, response_payload=mock_payload)
    service = LearningPathService(db=AsyncMock(), llm_client=llm)

    req = GenerateRoadmapRequest(
        topic="Matematika",
        subtopic="Pecahan",
        goal="Ujian",
        difficulty="beginner",
        diagnostic_score=30.0,
        misconceptions=["ADDS_NUM_DENOM_DIRECTLY"],
    )
    result = await service.generate_roadmap(req)

    assert result.title == "Roadmap Khusus Pecahan"
    assert len(result.steps) == 2
    assert result.steps[0].recommended_badge == "🎯 Rekomendasi Khusus Fondasi"
    assert result.is_fallback is False
    assert result.message is None


@pytest.mark.asyncio
async def test_generate_roadmap_fallback_on_error():
    llm = FakeLLMClient(should_fail=True)
    service = LearningPathService(db=AsyncMock(), llm_client=llm)

    req = GenerateRoadmapRequest(
        topic="Matematika",
        subtopic="Pecahan",
        diagnostic_score=40.0,
        misconceptions=["ADDS_NUM_DENOM_DIRECTLY"],
    )
    result = await service.generate_roadmap(req)

    assert result.is_fallback is True
    assert "kendala koneksi" in (result.message or "").lower()
    assert len(result.steps) == 5
    assert result.steps[0].recommended_badge == "🎯 Rekomendasi Khusus Fondasi"


@pytest.mark.asyncio
async def test_generate_lesson_intro_success():
    mock_payload = {
        "greeting": "Halo Budi!",
        "content": "Pecahan senilai seperti 1/2 martabak sama dengan 2/4 martabak.",
        "quick_prompts": ["Beri contoh soal", "Jelaskan lagi", "Mau latihan"],
    }
    llm = FakeLLMClient(should_fail=False, response_payload=mock_payload)
    service = LearningPathService(db=AsyncMock(), llm_client=llm)

    req = LessonIntroRequest(
        step_title="Pecahan Senilai",
        step_description="Materi senilai",
        topic="Matematika",
        subtopic="Pecahan",
        student_name="Budi",
    )
    result = await service.generate_lesson_intro(req)

    assert result.greeting == "Halo Budi!"
    assert len(result.quick_prompts) == 3
    assert result.is_fallback is False


@pytest.mark.asyncio
async def test_generate_lesson_intro_fallback_on_error():
    llm = FakeLLMClient(should_fail=True)
    service = LearningPathService(db=AsyncMock(), llm_client=llm)

    req = LessonIntroRequest(
        step_title="KPK Penyebut",
        step_description="Mencari KPK",
        topic="Matematika",
        subtopic="Pecahan",
    )
    result = await service.generate_lesson_intro(req)

    assert result.is_fallback is True
    assert len(result.quick_prompts) == 3
    assert "kendala koneksi" in (result.message or "").lower()
