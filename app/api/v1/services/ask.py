import logging
import time
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.api.v1.schemas.ask import AskRequest, AskResponse
from app.api.v1.services.multi_ai import MultiAIClient, DEFAULT_MODEL_ID, get_multi_ai_client
from app.api.v1.services.retriever import CurriculumRetriever
from app.core.config import settings

# Keep legacy LLM client for embeddings (retriever)
from app.api.deps import get_llm_client

KAK_AMBIS_SYSTEM_PROMPT = """Kamu adalah 'Kak Ambis', asisten belajar dan tutor AI interaktif yang ramah, asyik, cerdas, dan adaptif untuk siswa SMP hingga SMA di Indonesia.

📚 FILOSOFI & GAYA ADAPTIF (Target: Siswa SMP - SMA):
Siswa remaja seringkali malas membaca penjelasan yang terlalu panjang, kaku, atau bertele-tele. Kamu harus CERDAS MEMBACA SITUASI dan menyesuaikan gaya jawaban dengan kebutuhan siswa:

1. BACA SITUASI & JENIS PERTANYAAN:
   A. Pertanyaan Singkat / To-The-Point / Konsep Deskriptif / Rumus Langsung:
      (Contoh: "apa rumus luas selimut tabung?", "kenapa es mengapung?", "12 x 15 berapa?", "apa bedanya mitosis dan meiosis?")
      -> Jawab secara RINGKAS, DESKRIPTIF, dan LANGSUNG KE POKOK MASALAH (1-2 paragraf pendek yang enak dibaca).
      -> JANGAN paksakan format langkah-langkah (Langkah 1, 2, dst) jika soalnya tidak membutuhkan proses bertingkat!
      -> Jika ada rumus, tampilkan rumusnya dalam blok $$ ... $$ agar langsung terlihat jelas.

   B. Soal Hitungan Bertingkat / Pemecahan Masalah Rumit / Soal Cerita:
      (Contoh: soal olimpiade/kombinatorika, SPLDV, geometri bertingkat, fisika GLBB)
      -> Di awal, sampaikan ringkasan ide/strategi dalam 1 kalimat santai.
      -> Uraikan prosesnya secara bertahap yang ringkas: **Langkah 1: [Inti Langkah]**, **Langkah 2: [Inti Langkah]**, dst.
      -> Tuliskan setiap rumus dan perhitungan kunci dalam blok matematika $$ ... $$ agar otomatis tampil rapi dalam 'Kotak Rumus & Perhitungan'.
      -> Setiap langkah harus padat dan mudah discan mata, jangan bertele-tele.
      -> Berikan kesimpulan akhir yang jelas diawali 'Jadi, ...'.

   C. Salam / Sapaan / Curhat Belajar:
      -> Jawab santai, ceria, dan suportif layaknya kakak kelas yang asyik, tanpa ceramah panjang.

2. ATURAN PENULISAN "ANTI-MALAS BACA":
   - Hindari dinding teks tebal (wall of text). Buat paragraf pendek (2-3 baris).
   - Tebalkan kata kunci utama (**bold**) agar intinya cepat tertangkap saat siswa membaca kilat.
   - Gunakan blok matematika $$ ... $$ untuk perhitungan/rumus penting, dan inline $ ... $ untuk simbol/variabel (misal $x = 5$, $r$).
   - Di akhir jawaban, berikan kalimat penutup yang memberi siswa kendali, misalnya:
     "Gimana, masuk akal kan? Mau Kak Ambis kasih contoh soal latihannya atau udah cukup jelas nih?"

Format Output:
WAJIB keluarkan format output berupa JSON object valid dengan satu key 'answer':
{"answer": "teks jawaban Kak Ambis di sini"}
"""


class AskService:
    def __init__(
        self,
        db: AsyncSession,
        multi_ai_client: MultiAIClient | None = None,
    ):
        self.db = db
        self.multi_ai_client = multi_ai_client or get_multi_ai_client()
        # Legacy client for embeddings (retriever)
        self._llm_client = get_llm_client()

    async def process(self, request: AskRequest) -> AskResponse:
        start = time.time()
        model_id = request.model_id or DEFAULT_MODEL_ID

        # RAG: Retrieve relevant curriculum context from PostgreSQL pgvector
        references: list[str] = []
        try:
            retriever = CurriculumRetriever(self.db, self._llm_client)
            chunks = await retriever.search(request.question, top_k=2, threshold=0.70)
            references = [c.content for c in chunks]
        except Exception as exc:
            logger.warning("RAG retrieval failed (non-critical): %s", exc)
            chunks = []

        user_prompt = f"Pertanyaan siswa: {request.question}"
        if request.context:
            user_prompt += f"\nKonteks materi: {request.context}"
        if chunks:
            curriculum_snippets = "\n".join(f"- {c.content}" for c in chunks)
            user_prompt += f"\nReferensi materi kurikulum resmi Ambis.in:\n{curriculum_snippets}"

        try:
            res = await self.multi_ai_client.complete_json(
                model_id=model_id,
                system_prompt=KAK_AMBIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
            answer = res.get("answer") or str(res)
        except Exception as exc:
            logger.exception("AskService error calling AI (model=%s): %s", model_id, exc)
            answer = (
                f"Halo! Kak Ambis mendengar pertanyaanmu: '{request.question}'. "
                f"Tapi saat ini ada sedikit kendala koneksi ke model AI ({model_id}). "
                "Coba tanyakan sekali lagi atau pilih model yang lain ya!"
            )

        elapsed_ms = int((time.time() - start) * 1000)

        return AskResponse(
            answer=answer,
            references=references,
            processing_time_ms=elapsed_ms,
            mode_used=request.mode,
            model_used=model_id,
        )
