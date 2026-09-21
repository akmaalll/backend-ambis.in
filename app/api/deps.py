"""Shared per-process dependencies for API routes.

Not a DB dependency — see app/core/database.py's get_db for that (per-request
session). LLMClient holds a persistent httpx connection pool (see its own
docstring), so it belongs at process scope: one instance built at import
time and reused across requests, instead of opening/closing a client per call.
"""
from app.core.config import settings
from app.core.llm_client import LLMClient

_llm_client = LLMClient(settings.llm_base_url, settings.llm_api_key)


def get_llm_client() -> LLMClient:
    return _llm_client
