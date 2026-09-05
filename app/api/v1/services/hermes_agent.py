import asyncio
import json
import time
from typing import AsyncGenerator
from app.api.v1.schemas.hermes import (
    HermesAgentRequest,
    HermesAgentSSEEvent,
    HermesNonStreamResponse,
)


class HermesAgentService:
    """Mock Service Adapter for Hermes Agent with non-blocking async generator for SSE streaming."""

    def __init__(self):
        pass

    async def generate_stream(
        self, request: HermesAgentRequest
    ) -> AsyncGenerator[str, None]:
        """Generate simulated Server-Sent Events (SSE) stream for Hermes Agent."""
        start_time = time.time()
        scaffold_level = request.context_window.scaffold_level or 1
        prompt_text = request.prompt or "Halo Ambis.in"
        mode = request.mode or "ask"
        user_id_str = str(request.user_id) if request.user_id else "anonymous"

        # Helper to format SSE message
        def format_sse(event_type: str, data: dict) -> str:
            event = HermesAgentSSEEvent(event=event_type, data=data)
            return f"event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"

        # 1. Event: Thinking (Reasoning steps)
        thinking_steps = [
            f"Menganalisis prompt siswa: '{prompt_text[:60]}...'",
            f"Mengevaluasi learning state dan tingkat scaffolding aktif (Level {scaffold_level})...",
            "Mengidentifikasi potensi miskonsepsi (konseptual vs prosedural)...",
        ]
        for step in thinking_steps:
            await asyncio.sleep(0.1)  # non-blocking async sleep
            yield format_sse("thinking", {"thought": step, "timestamp": time.time()})

        # 2. Event: Tool Calling (Simulated tool execution based on mode)
        tools = request.tools_enabled or []
        if "diagnose_gap" in tools:
            await asyncio.sleep(0.15)
            tool_call_payload = {
                "tool_name": "diagnose_gap",
                "arguments": {
                    "prompt": prompt_text,
                    "mode": mode,
                    "current_scaffold_level": scaffold_level,
                },
            }
            yield format_sse("tool_call", tool_call_payload)

            # Simulated tool result
            await asyncio.sleep(0.1)
            tool_result_payload = {
                "tool_name": "diagnose_gap",
                "status": "success",
                "output": {
                    "identified_concept": "Pemecahan Masalah Bertahap",
                    "misconception_type": "procedural_gap",
                    "recommended_scaffold_level": scaffold_level,
                },
            }
            yield format_sse("tool_result", tool_result_payload)

        # 3. Event: Token Streaming (Simulated reply based on scaffolding ladder)
        response_text = self._build_scaffold_reply(prompt_text, scaffold_level, mode)
        words = response_text.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.04)  # natural token cadence
            yield format_sse("token", {"chunk": chunk, "index": i})

        # 4. Event: Done
        elapsed_ms = int((time.time() - start_time) * 1000)
        yield format_sse(
            "done",
            {
                "status": "completed",
                "user_id": user_id_str,
                "mode": mode,
                "scaffold_level": scaffold_level,
                "processing_time_ms": elapsed_ms,
                "model": "Hermes-Agent-v1-Stub",
            },
        )

    async def process_sync(self, request: HermesAgentRequest) -> HermesNonStreamResponse:
        """Fallback non-streaming execution for batch or testing."""
        start_time = time.time()
        await asyncio.sleep(0.2)
        scaffold_level = request.context_window.scaffold_level or 1
        prompt_text = request.prompt or "Halo Ambis.in"
        mode = request.mode or "ask"
        user_id_str = str(request.user_id) if request.user_id else "anonymous"

        reply = self._build_scaffold_reply(prompt_text, scaffold_level, mode)
        elapsed_ms = int((time.time() - start_time) * 1000)

        return HermesNonStreamResponse(
            user_id=user_id_str,
            reply=reply,
            tool_calls=[
                {
                    "tool_name": "diagnose_gap",
                    "status": "success",
                    "output": {"scaffold_level": scaffold_level},
                }
            ],
            scaffold_level=scaffold_level,
            processing_time_ms=elapsed_ms,
            mode_used=mode,
        )

    def _build_scaffold_reply(self, prompt: str, scaffold_level: int, mode: str) -> str:
        """Construct pedagogical response according to 5-Level Scaffolding Ladder."""
        if scaffold_level == 1:
            return (
                "Bagus sekali kamu sudah mencoba! Mari perhatikan kembali pola utama pada soal ini. "
                "Coba lihat komponen yang diketahui terlebih dahulu sebelum menentukan operasi hitung berikutnya."
            )
        elif scaffold_level == 2:
            return (
                "Coba kita telaah bersama: apa yang terjadi jika kamu menyederhanakan bentuk di ruas kiri terlebih dahulu? "
                "Bagaimana hubungan antara nilai variabel tersebut dengan yang ditanyakan?"
            )
        elif scaffold_level == 3:
            return (
                "Ingat kembali konsep dasarnya: ketika kita memindahkan suku ke ruas lain, tanda operasi akan berubah. "
                "Perhatikan bahwa suku sejenis harus dikelompokkan bersama terlebih dahulu."
            )
        elif scaffold_level == 4:
            return (
                "Mari kita pelajari contoh serupa: Jika 2x + 4 = 10, kita kurangkan kedua ruas dengan 4 menjadi 2x = 6, lalu x = 3. "
                "Sekarang, coba terapkan langkah yang sama pada soalmu!"
            )
        else:
            return (
                "Berikut adalah pembahasan lengkapnya langkah demi langkah. Pelajari alur logikanya, "
                "lalu kita akan coba satu soal latihan serupa agar pemahamanmu semakin mantap!"
            )
