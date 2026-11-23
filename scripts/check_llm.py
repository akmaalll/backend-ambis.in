"""Check a real (or fake) LLM endpoint against what this backend needs. No database.

Runs, in order:
  1. chat + response_format=json_object  (what Evaluator/Diagnostician/InterventionGenerator send)
  2. embeddings with `dimensions`         (what the retriever/backfill send; failure is non-critical)
  3. one canvas per intervention kind (guiding_question, hint, worked_example) generated from an
     in-memory sample exercise, validated by parse_visual_spec, counting LLM calls so a spec that
     needed the retry shows up as 2 calls.

Reads the same settings as the app (.env): LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_*,
EMBEDDING_MODEL, EMBEDDING_DIMENSIONS. Never prints the key.

Usage:
    python -m scripts.check_llm
"""
import asyncio
from uuid import uuid4

from app.core.config import settings
from app.core.llm_client import LLMClient, LLMResponseError
from app.models.curriculum import Exercise
from app.tools.intervention_generator import InterventionGenerator
from app.tools.policy_engine import PolicyDecision


class CountingClient:
    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.calls = 0

    async def complete_json(self, model, system_prompt, user_prompt):
        self.calls += 1
        return await self.inner.complete_json(model=model, system_prompt=system_prompt, user_prompt=user_prompt)


def _sample_exercise() -> Exercise:
    return Exercise(
        kind="short_answer",
        concept_id=uuid4(),
        question="Ibu punya 3/5 kg gula dan menambah 1/4 kg lagi. Berapa total gula Ibu sekarang?",
        correct_answer="17/20",
        solution_steps=["KPK dari 5 dan 4 = 20", "3/5 = 12/20, 1/4 = 5/20", "12/20 + 5/20 = 17/20"],
    )


def _report(ok: bool, label: str, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {label}{' - ' + detail if detail else ''}")
    return ok


async def main() -> int:
    if not settings.llm_base_url or not settings.llm_api_key:
        print("LLM_BASE_URL / LLM_API_KEY belum diisi di .env - tidak ada yang dicek.")
        return 2

    print(f"endpoint : {settings.llm_base_url}")
    print(f"model    : {settings.llm_model_intervention}")
    client = LLMClient(settings.llm_base_url, settings.llm_api_key)
    failures = 0

    try:
        try:
            reply = await client.complete_json(
                model=settings.llm_model_grading,
                system_prompt="You reply with JSON only.",
                user_prompt='Return exactly this JSON object: {"ok": true}',
            )
            failures += not _report(reply.get("ok") is True, "chat + json_object", f"reply={reply}")
        except LLMResponseError as exc:
            failures += not _report(False, "chat + json_object", str(exc)[:200])

        try:
            vectors = await client.embed(["pecahan"], model=settings.embedding_model, dimensions=settings.embedding_dimensions)
            _report(len(vectors[0]) == settings.embedding_dimensions, "embeddings (non-critical)", f"dim={len(vectors[0])}")
        except LLMResponseError as exc:
            _report(False, "embeddings (non-critical: RAG/backfill only)", str(exc)[:200])

        counting = CountingClient(client)
        generator = InterventionGenerator(db=None, llm_client=counting)
        for kind, rule in [
            ("guiding_question", "INITIAL_PROMPT"),
            ("hint", "FIRST_MISTAKE_HINT"),
            ("worked_example", "REPEATED_MISTAKES_WORKED_EXAMPLE"),
        ]:
            counting.calls = 0
            try:
                content = await generator.generate(
                    _sample_exercise(), PolicyDecision(kind=kind, rule_code=rule, reason="check")
                )
                types = ",".join(block.type for block in content.visual.blocks)
                _report(True, f"canvas {kind}", f"llm_calls={counting.calls} blocks=[{types}]")
            except LLMResponseError as exc:
                failures += not _report(False, f"canvas {kind}", f"llm_calls={counting.calls} {str(exc)[:240]}")
    finally:
        await client.aclose()

    print("selesai:", "ada yang gagal" if failures else "semua kebutuhan wajib lulus")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
