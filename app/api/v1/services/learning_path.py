import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.api.v1.schemas.learning_path import (
    GenerateRoadmapRequest,
    GenerateRoadmapResponse,
    LearningPathCreate,
    LessonIntroRequest,
    LessonIntroResponse,
    RoadmapStepSchema,
)
from app.core.config import settings
from app.core.llm_client import LLMClient
from app.models.learning_path import LearningPath

logger = logging.getLogger(__name__)


def _get_default_steps(
    subtopic: str,
    diagnostic_score: Optional[float] = None,
    misconceptions: Optional[list[str]] = None,
) -> list[RoadmapStepSchema]:
    if "pecahan" in subtopic.lower():
        needs_remediation = (
            diagnostic_score is not None and diagnostic_score < 50
        ) or (misconceptions and "ADDS_NUM_DENOM_DIRECTLY" in misconceptions)
        badge1 = "🎯 Rekomendasi Khusus Fondasi" if needs_remediation else None
        badge2 = "🎯 Rekomendasi Menyamakan KPK" if needs_remediation else None
        return [
            RoadmapStepSchema(
                id="step-1",
                title="Pecahan Senilai",
                description="Fondasi memahami pecahan senilai dengan representasi visual kue/persegi.",
                type="lesson",
                recommended_badge=badge1,
                has_quiz=False,
            ),
            RoadmapStepSchema(
                id="step-2",
                title="KPK Penyebut",
                description="Menentukan Kelipatan Persekutuan Terkecil untuk menyamakan penyebut berbeda.",
                type="lesson",
                recommended_badge=badge2,
                has_quiz=False,
            ),
            RoadmapStepSchema(
                id="step-3",
                title="Penjumlahan Pecahan Berpenyebut Beda",
                description="Materi inti: menyamakan penyebut dan menjumlahkan pembilang secara tepat.",
                type="lesson",
                has_quiz=False,
            ),
            RoadmapStepSchema(
                id="step-4",
                title="Latihan Terbimbing (Scaffolding)",
                description="Latihan soal interaktif dengan kartu bimbingan bertahap dari Kak Ambis.",
                type="practice",
                has_quiz=True,
            ),
            RoadmapStepSchema(
                id="step-5",
                title="Evaluasi & Uji Pemahaman",
                description="Uji pemahaman akhir dan kenaikan skor penguasaan konsep (mastery).",
                type="checkpoint",
                has_quiz=True,
            ),
        ]

    return [
        RoadmapStepSchema(
            id="step-1",
            title="Pengenalan Konsep Dasar",
            description=f"Memahami fondasi konsep {subtopic}.",
            type="lesson",
            has_quiz=False,
        ),
        RoadmapStepSchema(
            id="step-2",
            title="Teori & Rumus Utama",
            description="Mempelajari prinsip dan rumus penting.",
            type="lesson",
            has_quiz=False,
        ),
        RoadmapStepSchema(
            id="step-3",
            title="Latihan Terbimbing",
            description="Latihan soal dengan pendampingan Kak Ambis.",
            type="practice",
            has_quiz=True,
        ),
        RoadmapStepSchema(
            id="step-4",
            title="Evaluasi & Pemantapan",
            description="Uji pemahaman mandiri.",
            type="checkpoint",
            has_quiz=True,
        ),
    ]


class LearningPathService:
    def __init__(self, db: AsyncSession, llm_client: LLMClient | None = None):
        self.db = db
        self.llm_client = llm_client or get_llm_client()

    async def create(self, data: LearningPathCreate) -> LearningPath:
        model = LearningPath(**data.model_dump())
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def list_all(self) -> list[LearningPath]:
        result = await self.db.execute(select(LearningPath).order_by(LearningPath.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_id(self, path_id: UUID) -> LearningPath | None:
        result = await self.db.execute(select(LearningPath).where(LearningPath.id == path_id))
        return result.scalar_one_or_none()

    async def generate_roadmap(self, data: GenerateRoadmapRequest) -> GenerateRoadmapResponse:
        system_prompt = (
            "Kamu adalah arsitek kurikulum adaptif Ambis.in untuk siswa SMP (Kelas 7).\n"
            "Tugasmu adalah menyusun urutan langkah belajar (Roadmap) personal yang DINAMIS dan SPESIFIK untuk siswa berdasarkan data belajarnya.\n"
            "Pedoman:\n"
            "1. Jika siswa memiliki nilai diagnostik rendah (<50%) atau terdeteksi miskonsepsi (misal ADDS_NUM_DENOM_DIRECTLY: langsung jumlah pembilang & penyebut), "
            "WAJIB sertakan langkah perbaikan fondasi di awal dengan 'recommended_badge': '🎯 Rekomendasi Khusus Fondasi'.\n"
            "2. Jika nilai diagnostik tinggi (>=75%), ringkas langkah awal dan tambahkan langkah tantangan/soal cerita kontekstual.\n"
            "3. Susun 4 hingga 5 langkah yang logis dan menarik bagi siswa SMP.\n"
            "4. Format output WAJIB JSON object:\n"
            "{\n"
            '  "title": "Roadmap Belajar: ...",\n'
            '  "reasoning": "Penjelasan mengapa urutan ini dirancang khusus untuk siswa...",\n'
            '  "steps": [\n'
            '    {"id": "step-1", "title": "...", "description": "...", "type": "lesson", "recommended_badge": null, "has_quiz": false},\n'
            '    ...\n'
            "  ]\n"
            "}"
        )
        user_prompt = (
            f"Topik: {data.topic}\n"
            f"Subtopik: {data.subtopic}\n"
            f"Target Belajar Siswa: {data.goal or 'Memahami konsep dengan baik'}\n"
            f"Level: {data.difficulty or 'Pemula'}\n"
            f"Nilai Asesmen Diagnostik: {data.diagnostic_score if data.diagnostic_score is not None else 'Belum tes'}\n"
            f"Miskonsepsi yang Terdeteksi: {data.misconceptions or []}\n"
        )
        try:
            res = await self.llm_client.complete_json(
                model=settings.llm_model_intervention,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            raw_steps = res.get("steps", [])
            steps = []
            for i, s in enumerate(raw_steps):
                steps.append(
                    RoadmapStepSchema(
                        id=s.get("id", f"step-{i+1}"),
                        title=s.get("title", f"Tahap {i+1}"),
                        description=s.get("description", ""),
                        type=s.get("type", "lesson"),
                        recommended_badge=s.get("recommended_badge"),
                        has_quiz=s.get("has_quiz", s.get("type") in ("practice", "checkpoint")),
                    )
                )
            if not steps:
                steps = _get_default_steps(data.subtopic, data.diagnostic_score, data.misconceptions)
            return GenerateRoadmapResponse(
                title=res.get("title", f"Roadmap Belajar: {data.subtopic}"),
                reasoning=res.get("reasoning", "Roadmap telah dirancang khusus berdasarkan profil dan hasil pemahamanmu."),
                steps=steps,
                is_fallback=False,
            )
        except Exception as exc:
            logger.warning("Failed to generate dynamic roadmap via LLM: %s", exc)
            fallback_steps = _get_default_steps(data.subtopic, data.diagnostic_score, data.misconceptions)
            return GenerateRoadmapResponse(
                title=f"Roadmap Belajar: {data.subtopic}",
                reasoning="Roadmap belajar terstruktur disusun berdasarkan kurikulum inti.",
                steps=fallback_steps,
                is_fallback=True,
                message="Maaf ya, Kak Ambis sedang mengalami sedikit kendala koneksi ke server AI saat menyusun roadmap otomatis. Untuk sementara, Kak Ambis siapkan rekomendasi kurikulum standar ini ya!",
            )

    async def generate_lesson_intro(self, data: LessonIntroRequest) -> LessonIntroResponse:
        system_prompt = (
            "Kamu adalah 'Kak Ambis', tutor AI adaptif untuk siswa SMP di Ambis.in.\n"
            "Siswa baru saja membuka tahap belajar. JANGAN BIARKAN CHAT KOSONG!\n"
            "Tugasmu adalah PROAKTIF MENYAPA DAN MEMBUKA PEMBELAJARAN dengan ramah, ceria, dan memikat:\n"
            "1. Sapa siswa dengan hangat.\n"
            "2. Jelaskan konsep inti secara ringkas (1-2 paragraf pendek) menggunakan analogi nyata (misal kue, martabak, atau cokelat) dan rumus matematika KaTeX ($ ... $ atau $$ ... $$).\n"
            "3. Buat 3 pertanyaan / tombol pemantik ('quick_prompts') yang bisa dipilih siswa untuk melanjutkan interaksi.\n"
            "Format output WAJIB JSON:\n"
            "{\n"
            '  "greeting": "Halo! ...",\n'
            '  "content": "Penjelasan pengantar materi dan analogi ...",\n'
            '  "quick_prompts": ["Beri contoh soal sederhana", "Jelaskan analoginya lebih dalam", "Aku sudah paham, ayo langsung latihan"]\n'
            "}"
        )
        user_prompt = (
            f"Tahap Belajar: {data.step_title}\n"
            f"Deskripsi Tahap: {data.step_description}\n"
            f"Materi: {data.topic} - {data.subtopic}\n"
            f"Nama Siswa: {data.student_name or 'Siswa'}\n"
        )
        try:
            res = await self.llm_client.complete_json(
                model=settings.llm_model_intervention,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            return LessonIntroResponse(
                greeting=res.get("greeting", f"Halo! Selamat datang di tahap {data.step_title}! 👋"),
                content=res.get("content", f"Di tahap ini kita akan membahas tentang {data.step_title}. Siap belajar bareng Kak Ambis?"),
                quick_prompts=res.get("quick_prompts", [
                    "Beri contoh soal sederhana",
                    "Jelaskan rumus konsep ini",
                    "Aku sudah paham, mau latihan soal",
                ]),
                is_fallback=False,
            )
        except Exception as exc:
            logger.warning("Failed to generate lesson intro via LLM: %s", exc)
            fallback_content = (
                f"Di tahap **{data.step_title}**, kita akan mempelajari konsep {data.subtopic}. "
                "Bayangkan sebuah martabak yang dipotong-potong. Untuk menjumlahkan atau membandingkannya, ukuran potongannya harus kita samakan terlebih dahulu! 🍰"
            )
            return LessonIntroResponse(
                greeting=f"Halo! Semangat belajar di tahap {data.step_title}! 👋",
                content=fallback_content,
                quick_prompts=[
                    "Beri contoh soal sederhana",
                    "Jelaskan konsepnya lebih santai",
                    "Aku sudah paham, mau latihan soal",
                ],
                is_fallback=True,
                message="Maaf ya, Kak Ambis sedang mengalami sedikit kendala koneksi ke server AI saat menyiapkan pembuka otomatis. Tapi tenang, kamu tetap bisa belajar dengan panduan awal ini!",
            )
