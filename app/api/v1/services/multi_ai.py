"""
multi_ai.py - Multi-provider AI client for Ambis.in

Mendukung 3 provider gratis:
  - gemini/*      : Google Gemini via REST API
  - groq/*        : Groq via OpenAI-compatible REST API
  - openrouter/*  : OpenRouter via OpenAI-compatible REST API

Semua provider diakses lewat interface yang sama:
    client = MultiAIClient()
    response = await client.complete(model_id, system_prompt, user_prompt)
"""
import asyncio
import json
import logging
import re

import httpx
from typing import AsyncGenerator

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Registry - daftar model yang tersedia (verified working)
# ---------------------------------------------------------------------------
AVAILABLE_MODELS = [
    {
        "id": "gemini/gemini-3.5-flash-lite",
        "name": "Kak Ambis AI",
        "provider": "9router",
        "provider_label": "9router Gateway",
        "description": "Model tutor adaptif cerdas & cepat via gateway 9router",
        "is_free": True,
        "icon": "⚡",
    },
]

DEFAULT_MODEL_ID = "gemini/gemini-3.5-flash-lite"


def _parse_provider(model_id: str) -> tuple[str, str]:
    """Parse provider dari model_id."""
    if not model_id:
        return "9router", DEFAULT_MODEL_ID
    parts = model_id.split("/", 1)
    if len(parts) == 1:
        return "9router", parts[0]
    return parts[0], parts[1]


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences like ```json ... ```"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Google Gemini Provider
# ---------------------------------------------------------------------------
async def _complete_gemini(model_name: str, system_prompt: str, user_prompt: str) -> str:
    """Call Google Gemini via REST API."""
    api_key = settings.gemini_api_key
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in .env")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Gemini response format: {data}") from e


async def _stream_gemini(
    model_name: str, system_prompt: str, user_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream Gemini via REST API SSE, yield each text chunk."""
    api_key = settings.gemini_api_key
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in .env")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:streamGenerateContent?key={api_key}"
    )
    payload: dict = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
            "stream": True,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    candidate = data.get("candidates", [{}])[0]
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text
                except (KeyError, IndexError, TypeError):
                    continue


# ---------------------------------------------------------------------------
# Groq Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Groq Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
async def _complete_groq(model_name: str, system_prompt: str, user_prompt: str) -> str:
    """Call Groq via OpenAI-compatible REST API."""
    api_key = settings.groq_api_key
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set in .env")

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected Groq response format: {data}") from e


async def _stream_groq(
    model_name: str, system_prompt: str, user_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream Groq via OpenAI-compatible /chat/completions?stream=true."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload: dict = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True,
    }
    headers: dict = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or line == "[DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk_obj = json.loads(line[len("data: "):])
                    except json.JSONDecodeError:
                        continue
                    delta = chunk_obj.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield text


# ---------------------------------------------------------------------------
# OpenRouter Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
async def _complete_openrouter(model_name: str, system_prompt: str, user_prompt: str) -> str:
    """Call OpenRouter via OpenAI-compatible REST API."""
    api_key = settings.openrouter_api_key
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set in .env")

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ambis.in",
        "X-Title": "Ambis.in",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected OpenRouter response format: {data}") from e


async def _stream_openrouter(
    model_name: str, system_prompt: str, user_prompt: str
) -> AsyncGenerator[str, None]:
    """Stream OpenRouter via OpenAI-compatible /chat/completions?stream=true."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload: dict = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True,
    }
    headers: dict = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ambis.in",
        "X-Title": "Ambis.in",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or line == "[DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk_obj = json.loads(line[len("data: "):])
                    except json.JSONDecodeError:
                        continue
                    delta = chunk_obj.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield text


# ---------------------------------------------------------------------------
# 9router Gateway Provider (OpenAI-compatible)
# ---------------------------------------------------------------------------
async def _complete_9router(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    messages: list[dict[str, str]] | None = None,
) -> str:
    """Call 9router via OpenAI-compatible REST API with automatic retry and model fallback."""
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"

    if messages:
        payload_messages = messages
    else:
        payload_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    models_to_try = [model_name]
    fallback_model = "gemini/gemini-2.5-flash"
    if model_name != fallback_model:
        models_to_try.append(fallback_model)

    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt_model in models_to_try:
        payload = {
            "model": attempt_model,
            "messages": payload_messages,
            "temperature": 0.7,
            "max_tokens": 8192,
            "stream": False,
        }

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code != 200:
                        err_text = response.text
                        logger.warning(
                            "9router complete error (model=%s, status=%s): %s",
                            attempt_model,
                            response.status_code,
                            err_text[:200],
                        )
                        if response.status_code in (502, 503, 504, 429):
                            await asyncio.sleep(1.2)
                            continue
                        response.raise_for_status()

                    data = response.json()
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                logger.warning("Complete attempt %d for model %s failed: %s", attempt + 1, attempt_model, e)
                await asyncio.sleep(1.0)

    if last_error:
        raise last_error
    raise RuntimeError("9router request failed after all attempts and fallbacks.")


async def _stream_9router(
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    messages: list[dict[str, str]] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream 9router via OpenAI-compatible /chat/completions?stream=true with automatic retry and model fallback."""
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"

    if messages:
        payload_messages = messages
    else:
        payload_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    models_to_try = [model_name]
    fallback_model = "gemini/gemini-2.5-flash"
    if model_name != fallback_model:
        models_to_try.append(fallback_model)

    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt_model in models_to_try:
        payload = {
            "model": attempt_model,
            "messages": payload_messages,
            "temperature": 0.7,
            "max_tokens": 8192,
            "stream": True,
        }

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream("POST", url, json=payload, headers=headers) as response:
                        if response.status_code != 200:
                            err_bytes = await response.aread()
                            err_msg = err_bytes.decode(errors="replace")
                            logger.warning(
                                "9router stream error (model=%s, status=%s): %s",
                                attempt_model,
                                response.status_code,
                                err_msg[:200],
                            )
                            if response.status_code in (502, 503, 504, 429):
                                await asyncio.sleep(1.2)
                                continue
                            response.raise_for_status()

                        streamed_any = False
                        async for raw_line in response.aiter_lines():
                            line = raw_line.strip()
                            if not line or line == "[DONE]":
                                continue
                            if line.startswith("data: "):
                                try:
                                    chunk_obj = json.loads(line[len("data: "):])
                                except json.JSONDecodeError:
                                    continue
                                delta = chunk_obj.get("choices", [{}])[0].get("delta", {})
                                text = delta.get("content")
                                if text:
                                    streamed_any = True
                                    yield text

                        if streamed_any:
                            return
            except Exception as e:
                last_error = e
                logger.warning("Stream attempt %d for model %s failed: %s", attempt + 1, attempt_model, e)
                await asyncio.sleep(1.0)

    if last_error:
        raise last_error



# ---------------------------------------------------------------------------
# MultiAIClient - unified interface
# ---------------------------------------------------------------------------
class MultiAIClient:
    """
    Unified multi-provider AI client.
    Routes via 9router when LLM_BASE_URL is configured, or direct providers.
    Supports multi-turn conversation messages.
    """

    async def complete(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        """Call the selected provider or 9router gateway."""
        if settings.llm_base_url and settings.llm_api_key:
            target_model = model_id or settings.llm_model_intervention or DEFAULT_MODEL_ID
            logger.info("MultiAIClient: routing via 9router model=%s (messages=%d)", target_model, len(messages) if messages else 1)
            return await _complete_9router(target_model, system_prompt, user_prompt, messages=messages)

        provider, model_name = _parse_provider(model_id)
        logger.info("MultiAIClient: calling provider=%s model=%s", provider, model_name)

        if provider == "gemini":
            return await _complete_gemini(model_name, system_prompt, user_prompt)
        elif provider == "groq":
            return await _complete_groq(model_name, system_prompt, user_prompt)
        elif provider == "openrouter":
            return await _complete_openrouter(model_name, system_prompt, user_prompt)
        else:
            raise ValueError(
                f"Unknown provider: {provider!r}. Supported: gemini, groq, openrouter, 9router"
            )

    async def complete_json(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        messages: list[dict[str, str]] | None = None,
    ) -> dict:
        """
        Call provider and parse JSON from the response.
        Falls back to returning raw text as {"answer": "..."} if JSON parsing fails.
        """
        raw = await self.complete(model_id, system_prompt, user_prompt, messages=messages)
        cleaned = _strip_json_fences(raw)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract first {...} block
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return {"answer": raw}
            else:
                return {"answer": raw}

        if not isinstance(parsed, dict):
            return {"answer": raw}

        return parsed

    async def stream_text(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        messages: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream response from 9router gateway or legacy direct providers."""
        if settings.llm_base_url and settings.llm_api_key:
            target_model = model_id or settings.llm_model_intervention or DEFAULT_MODEL_ID
            logger.info(
                "MultiAIClient.stream_text: routing via 9router model=%s (messages=%d)",
                target_model,
                len(messages) if messages else 1,
            )
            async for chunk in _stream_9router(
                target_model, system_prompt, user_prompt, messages=messages
            ):
                yield chunk
            return

        provider, model_name = _parse_provider(model_id)

        logger.info(
            "MultiAIClient.stream_text: provider=%s model=%s", provider, model_name
        )

        if provider == "gemini":
            async for chunk in _stream_gemini(
                model_name, system_prompt, user_prompt
            ):
                yield chunk
        elif provider == "groq":
            async for chunk in _stream_groq(
                model_name, system_prompt, user_prompt
            ):
                yield chunk
        elif provider == "openrouter":
            async for chunk in _stream_openrouter(
                model_name, system_prompt, user_prompt
            ):
                yield chunk
        else:
            raise ValueError(
                f"Unknown provider: {provider!r}. Supported: gemini, groq, openrouter, 9router"
            )


# Singleton instance for dependency injection
_multi_ai_client = MultiAIClient()


def get_multi_ai_client() -> MultiAIClient:
    return _multi_ai_client
