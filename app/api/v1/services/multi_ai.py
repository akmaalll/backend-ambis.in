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
    # --- Groq ---
    {
        "id": "groq/groq/compound",
        "name": "Compound (Groq)",
        "provider": "groq",
        "provider_label": "Groq",
        "description": "Model flagship Groq, powerful & versatile",
        "is_free": True,
        "icon": "⚡",
    },
    {
        "id": "groq/groq/compound-mini",
        "name": "Compound Mini (Groq)",
        "provider": "groq",
        "provider_label": "Groq",
        "description": "Versi ringkas Compound - lebih cepat",
        "is_free": True,
        "icon": "⚡",
    },
    {
        "id": "groq/openai/gpt-oss-20b",
        "name": "GPT-OSS 20B (Groq)",
        "provider": "groq",
        "provider_label": "Groq",
        "description": "OpenAI OSS 20B berjalan di Groq",
        "is_free": True,
        "icon": "⚡",
    },
    {
        "id": "groq/qwen/qwen3.8-27b",
        "name": "Qwen 3.8 27B (Groq)",
        "provider": "groq",
        "provider_label": "Groq",
        "description": "Alibaba Qwen 27B - pintar & akurat",
        "is_free": True,
        "icon": "⚡",
    },
    # --- Google Gemini ---
    {
        "id": "gemini/gemini-3.6-flash",
        "name": "Gemini 3.6 Flash",
        "provider": "google",
        "provider_label": "Google Gemini",
        "description": "Model terbaru Google, cepat & canggih",
        "is_free": True,
        "icon": "🔵",
    },
    # --- OpenRouter ---
    {
        "id": "openrouter/deepseek/deepseek-v4-flash-0731:free",
        "name": "DeepSeek V4 Flash",
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "description": "DeepSeek V4 Flash gratis via OpenRouter",
        "is_free": True,
        "icon": "🌐",
    },
    {
        "id": "openrouter/nvidia/nemotron-3.5-lightning:free",
        "name": "Nemotron 3.5 Lightning",
        "provider": "openrouter",
        "provider_label": "OpenRouter",
        "description": "NVIDIA Nemotron gratis via OpenRouter",
        "is_free": True,
        "icon": "🌐",
    },
]

DEFAULT_MODEL_ID = "groq/groq/compound"


def _parse_provider(model_id: str) -> tuple[str, str]:
    """
    Parse provider dari model_id.
    Format: 'provider/model-name' atau 'provider/org/model-name'
    Contoh:
      'groq/groq/compound'         -> ('groq', 'groq/compound')
      'gemini/gemini-3.6-flash'    -> ('gemini', 'gemini-3.6-flash')
      'openrouter/deepseek/...'    -> ('openrouter', 'deepseek/...')
    """
    parts = model_id.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid model_id format: {model_id!r}. Expected 'provider/model-name'")
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
# MultiAIClient - unified interface
# ---------------------------------------------------------------------------
class MultiAIClient:
    """
    Unified multi-provider AI client.
    Supports: gemini/*, groq/*, openrouter/*
    """

    async def complete(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Call the selected provider and return raw text response."""
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
                f"Unknown provider: {provider!r}. Supported: gemini, groq, openrouter"
            )

    async def complete_json(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """
        Call provider and parse JSON from the response.
        Falls back to returning raw text as {"answer": "..."} if JSON parsing fails.
        """
        raw = await self.complete(model_id, system_prompt, user_prompt)
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
    ) -> AsyncGenerator[str, None]:
        """Stream response from the selected provider, yield each text chunk.

        Gemini uses raw SSE lines; Groq & OpenRouter use OpenAI-format SSE
        (data: {...}) — both are normalized to plain text chunks here.
        """
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
                f"Unknown provider: {provider!r}. Supported: gemini, groq, openrouter"
            )


# Singleton instance for dependency injection
_multi_ai_client = MultiAIClient()


def get_multi_ai_client() -> MultiAIClient:
    return _multi_ai_client
