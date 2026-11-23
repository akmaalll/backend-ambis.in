"""SSE chat endpoint — streaming & non-streaming multi-model chat with persistent DB memory."""
import json
import logging
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.services.multi_ai import (
    DEFAULT_MODEL_ID,
    get_multi_ai_client,
)
from app.api.v1.services.student_memory import (
    DEFAULT_STUDENT_ID,
    StudentMemoryService,
)
from app.api.v1.services.canvas_builder import (
    should_open_canvas,
    build_canvas_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


DEFAULT_SYSTEM_PROMPT = (
    "Kamu adalah 'Kak Ambis', tutor AI yang ramah, asyik, dan suportif untuk siswa SMP di Indonesia.\n"
    "Pedoman Format Menjawab (Target: Siswa SMP — Rapi, Ringkas, & Bersih):\n"
    "1. ATURAN EMOJI: DILARANG KERAS menggunakan emoji dalam bentuk apa pun di seluruh jawaban.\n"
    "2. Nada Bicara: Santai, hangat, menyemangati, dan to-the-point layaknya kakak kelas yang baik.\n"
    "3. Penulisan Matematika: Gunakan KaTeX yang bersih. Gunakan $$ ... $$ untuk rumus utama (misal: $$ L = \\frac{1}{2} \\times a \\times t $$) atau $ ... $ untuk variabel/simbol ($x$, $cm^2$). JANGAN menumpuk rumus dengan kata-kata berulang di dalam tanda kurung.\n"
    "4. Penulisan Kode (Python/dsb): WAJIB gunakan blok kode markdown lengkap (```python ... ```) dengan sintaks yang benar dan rapi.\n"
    "5. Struktur Rapi: Gunakan judul bagian singkat dengan ### (misal: ### Cara Perbaikan, ### Kode yang Benar, ### Tips Tambahan).\n"
    "6. Anti-Malas Baca: Buat paragraf pendek (2-3 baris). Tebalkan kata kunci penting (**bold**).\n"
    "7. Format Alur Langkah & Canvas: Saat siswa meminta penjelasan bertahap, pemecahan soal, kode, atau menyebut 'canvas'/'langkah', gunakan penomoran terstruktur (Langkah 1: ..., Langkah 2: ..., dst.) dan selesaikan jawaban secara tuntas sampai akhir tanpa terpotong.\n"
    "8. Penutup: Berikan kesimpulan akhir yang jelas dan kalimat penyemangat singkat."
)


class StudentContext(BaseModel):
    student_id: str | None = None
    name: str | None = None
    grade: str | None = None
    goal: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    difficulty: str | None = None
    facts: list[str] | None = None
    previous_sessions: list[str] | None = None


class StudentMemorySaveRequest(BaseModel):
    student_id: str = DEFAULT_STUDENT_ID
    name: str | None = None
    grade: str | None = None
    goal: str | None = None
    topic: str | None = None
    facts: list[str] | None = None
    summary: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatStreamRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    prompt: str = Field(..., min_length=1, max_length=10000)
    messages: list[ChatMessage] | None = None
    student_context: StudentContext | None = None
    model_id: str = Field(default=DEFAULT_MODEL_ID)
    system_prompt: str | None = None
    stream: bool = True


@router.get("/memory")
async def get_student_memory(
    student_id: str = Query(default=DEFAULT_STUDENT_ID),
    db: AsyncSession = Depends(get_db),
):
    """Ambil memori jangka panjang siswa dari PostgreSQL database."""
    service = StudentMemoryService(db)
    return await service.get_memory(student_id)


@router.post("/memory")
async def save_student_memory(
    payload: StudentMemorySaveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Simpan atau perbarui memori jangka panjang siswa di database."""
    service = StudentMemoryService(db)
    return await service.save_memory(
        student_id=payload.student_id,
        name=payload.name,
        grade=payload.grade,
        goal=payload.goal,
        topic=payload.topic,
        facts=payload.facts,
        summary=payload.summary,
    )


@router.post("/stream")
async def chat_stream(
    request: ChatStreamRequest,
    db: AsyncSession = Depends(get_db),
):
    """Chat dengan streaming SSE (default) atau non-streaming JSON (mendukung memori 1 sesi penuh & memori jangka panjang database)."""
    system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT

    memory_service = StudentMemoryService(db)
    student_id = (
        request.student_context.student_id
        if (request.student_context and request.student_context.student_id)
        else DEFAULT_STUDENT_ID
    )

    # 1. Cek apakah ada perkenalan identitas dari prompt pesan user saat ini
    extracted = memory_service.extract_identity_from_text(request.prompt)

    # 2. Ambil data memori tersimpan dari database PostgreSQL
    db_memory = await memory_service.get_memory(student_id)

    # Tentukan nama dan identitas siswa (prioritas: deteksi baru > payload request > DB tersimpan)
    raw_name = (
        extracted.get("name")
        or (request.student_context and request.student_context.name)
        or db_memory.get("name")
    )
    student_name = raw_name if (raw_name and StudentMemoryService._is_valid_name(raw_name)) else None

    student_grade = (
        extracted.get("grade")
        or (request.student_context and request.student_context.grade)
        or db_memory.get("grade")
    )

    # Jika ada deteksi baru atau nama berubah, perbarui ke database
    if extracted.get("name") or extracted.get("grade"):
        try:
            await memory_service.save_memory(
                student_id=student_id,
                name=student_name,
                grade=student_grade,
                facts=[f"Memperkenalkan diri sebagai {student_name}"] if student_name else None,
            )
        except Exception as err:
            logger.warning("Auto-save memory from prompt warning: %s", err)

    # 3. Rakit instruksi memori jangka panjang ke dalam System Prompt
    memories = ["\n[MEMORI JANGKA PANJANG & PROFIL BELAJAR SISWA]"]

    if student_name:
        memories.append(f"- NAMA PANGGILAN RESMI SISWA: {student_name}")
        memories.append("- ATURAN MUTLAK IDENTITAS SISWA:")
        memories.append(f"  * Siswa ini BERNAMA '{student_name}'. Kamu SUDAH MENGENAL siswa ini.")
        memories.append(f"  * Jika siswa bertanya 'siapa namaku?', 'namaku siapa?', 'kamu ingat namaku?', atau sejenisnya, JAWAB LANGSUNG DENGAN YAKIN: 'Nama kamu adalah {student_name}! Kak Ambis pasti ingat dong.'")
        memories.append("  * DILARANG KERAS bertanya 'siapa namamu?', meminta siswa memperkenalkan diri lagi, atau bersikap seperti orang asing yang baru pertama kali kenal!")
        memories.append(f"  * Sapalah siswa secara akrab, hangat, dan sebut namanya (misal: 'Halo {student_name}!', 'Hai {student_name}!').")
        memories.append("  * Pertahankan rasa keakraban antar-sesi seolah kamu adalah kakak kelas yang selalu mendampinginya.")
    else:
        memories.append("- STATUS IDENTITAS: Siswa belum memberitahukan namanya.")
        memories.append("  * Jika siswa bertanya 'siapa namaku?' atau 'namaku siapa?', jawab dengan santai dan ramah bahwa kamu belum tahu namanya dan persilakan dia berkenalan.")

    if student_grade:
        memories.append(f"- Jenjang/Kelas Siswa: {student_grade}")

    if request.student_context:
        ctx = request.student_context
        if ctx.goal:
            memories.append(f"- Target Belajar: {ctx.goal}")
        if ctx.topic or ctx.subtopic:
            memories.append(f"- Minat Materi: {ctx.topic} {f'({ctx.subtopic})' if ctx.subtopic else ''}")
        if ctx.difficulty:
            memories.append(f"- Tingkat Pemahaman: {ctx.difficulty}")
        if ctx.previous_sessions:
            memories.append("- Riwayat Sesi Percakapan Sebelumnya:")
            for s in ctx.previous_sessions:
                memories.append(f"  * {s}")

    db_facts = db_memory.get("facts") or []
    if db_facts:
        memories.append("- Catatan Pembelajaran Sebelumnya:")
        for f in db_facts[-5:]:
            memories.append(f"  * {f}")

    memories.append(
        "- PANDUAN KESINAMBUNGAN BELAJAR: Kamu mengingat profil dan topik-topik yang pernah dipelajari siswa ini sebelumnya. "
        "Jika siswa membuat percakapan baru atau menyinggung materi terdahulu, tunjukkan pemahamanmu secara hangat dan nyambung."
    )
    system_prompt += "\n" + "\n".join(memories)

    # 4. Build conversation messages payload for full current session
    history_messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]

    if request.messages:
        for m in request.messages:
            r = "assistant" if m.role == "assistant" else "user"
            history_messages.append({"role": r, "content": m.content})
        # If the last message in history is not current prompt, append it
        if not history_messages or history_messages[-1]["content"] != request.prompt:
            history_messages.append({"role": "user", "content": request.prompt})
    else:
        history_messages.append({"role": "user", "content": request.prompt})

    if not request.stream:
        client = get_multi_ai_client()
        start = time.time()
        answer = await client.complete(
            request.model_id,
            system_prompt,
            request.prompt,
            messages=history_messages,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "answer": answer,
            "model_used": request.model_id,
            "processing_time_ms": elapsed_ms,
            "student_memory": {
                "student_id": student_id,
                "name": student_name,
                "grade": student_grade,
            },
        }

    client = get_multi_ai_client()

    async def event_generator():
        start = time.time()
        total_chars = 0

        # Kirim status inisiasi & informasi memori aktif
        yield (
            f"event: thinking\n"
            f"data: {json.dumps({'status': 'memulai...', 'model': request.model_id}, ensure_ascii=False)}\n\n"
        )

        valid_name = student_name if (student_name and StudentMemoryService._is_valid_name(student_name)) else None

        if valid_name or student_grade:
            yield (
                f"event: memory\n"
                f"data: {json.dumps({'student_id': student_id, 'name': valid_name, 'grade': student_grade}, ensure_ascii=False)}\n\n"
            )

        full_response = ""
        try:
            async for chunk in client.stream_text(
                request.model_id,
                system_prompt,
                request.prompt,
                messages=history_messages,
            ):
                full_response += chunk
                total_chars += len(chunk)
                yield (
                    f"event: token\n"
                    f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                )
        except Exception as exc:
            err_str = str(exc)
            if "503" in err_str or "Service Unavailable" in err_str:
                user_msg = "Layanan model AI sedang mengalami beban tinggi sementara (503 Service Unavailable). Silakan klik kirim ulang pesanmu."
            elif "502" in err_str or "504" in err_str or "timeout" in err_str.lower():
                user_msg = "Koneksi ke gateway AI mengalami batas waktu (timeout). Silakan coba kirim kembali."
            else:
                user_msg = err_str

            yield (
                f"event: error\n"
                f"data: {json.dumps({'message': user_msg}, ensure_ascii=False)}\n\n"
            )
            return

        # Emit canvas payload when response warrants deep explanation
        if full_response and should_open_canvas(request.prompt, full_response):
            try:
                canvas = build_canvas_payload(request.prompt, full_response)
                canvas_dict = {
                    "title": canvas.title,
                    "subject": canvas.subject,
                    "analogy": canvas.analogy,
                    "concept": canvas.concept,
                    "core_formula": canvas.core_formula,
                    "steps": [
                        {
                            "number": s.number,
                            "title": s.title,
                            "body": s.body,
                            "formula": s.formula,
                            "short_desc": s.short_desc,
                        }
                        for s in canvas.steps
                    ],
                    "summary": canvas.summary,
                    "final_answer": canvas.final_answer,
                    "raw_content": canvas.raw_content,
                }
                yield (
                    f"event: canvas\n"
                    f"data: {json.dumps(canvas_dict, ensure_ascii=False)}\n\n"
                )
            except Exception as canvas_err:
                logger.warning("Canvas build error: %s", canvas_err)

        elapsed_ms = int((time.time() - start) * 1000)
        yield (
            f"event: done\n"
            f"data: {json.dumps({'model_used': request.model_id, 'processing_time_ms': elapsed_ms, 'total_chars': total_chars, 'student_name': valid_name}, ensure_ascii=False)}\n\n"
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

