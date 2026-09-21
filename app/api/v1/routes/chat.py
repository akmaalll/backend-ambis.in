"""SSE chat endpoint — streaming & non-streaming multi-model chat."""
import json
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.v1.services.multi_ai import (
    DEFAULT_MODEL_ID,
    MultiAIClient,
    get_multi_ai_client,
)

router = APIRouter(prefix="/chat", tags=["Chat"])


DEFAULT_SYSTEM_PROMPT = (
    "Kamu adalah Kak Ambis, asisten belajar dan tutor AI yang ramah, "
    "asyik, dan cerdas untuk siswa SMP-SMA di Indonesia. "
    "Jawab dalam bahasa Indonesia yang santai, jelas, dan mudah dipahami. "
    "Gunakan penjelasan bertahap untuk soal hitungan, dan jawaban ringkas "
    "untuk pertanyaan konseptual."
)


class ChatStreamRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    prompt: str = Field(..., min_length=1, max_length=10000)
    model_id: str = Field(default=DEFAULT_MODEL_ID)
    system_prompt: str | None = None
    stream: bool = True


@router.post("/stream")
async def chat_stream(request: ChatStreamRequest):
    """Chat dengan streaming SSE (default) atau non-streaming JSON."""
    if not request.stream:
        client = get_multi_ai_client()
        start = time.time()
        answer = await client.complete(
            request.model_id,
            request.system_prompt or DEFAULT_SYSTEM_PROMPT,
            request.prompt,
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "answer": answer,
            "model_used": request.model_id,
            "processing_time_ms": elapsed_ms,
        }

    client = get_multi_ai_client()
    system_prompt = request.system_prompt or DEFAULT_SYSTEM_PROMPT

    async def event_generator():
        start = time.time()
        total_chars = 0

        yield (
            f"event: thinking\n"
            f"data: {json.dumps({'status': 'memulai...', 'model': request.model_id}, ensure_ascii=False)}\n\n"
        )

        try:
            async for chunk in client.stream_text(request.model_id, system_prompt, request.prompt):
                total_chars += len(chunk)
                yield (
                    f"event: token\n"
                    f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                )
        except Exception as exc:
            yield (
                f"event: error\n"
                f"data: {json.dumps({'message': str(exc)}, ensure_ascii=True)}\n\n"
            )
            return

        elapsed_ms = int((time.time() - start) * 1000)
        yield (
            f"event: done\n"
            f"data: {json.dumps({'model_used': request.model_id, 'processing_time_ms': elapsed_ms, 'total_chars': total_chars}, ensure_ascii=False)}\n\n"
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
