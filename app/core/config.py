from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ambis.in API"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://postgres:root@127.0.0.1:5432/ambisin_db"
    redis_url: str = "redis://localhost:6379"

    # JWT & Auth
    secret_key: str = "ambis-in-secret-key-change-in-production-2024"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # OpenAI-compatible LLM endpoint for chat (grading/diagnosis/intervention)
    # AND embeddings (same base URL + key). Gemini:
    # https://generativelanguage.googleapis.com/v1beta/openai
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model_grading: str = "PLACEHOLDER_MODEL"
    llm_model_diagnosis: str = "PLACEHOLDER_MODEL"
    llm_model_intervention: str = "PLACEHOLDER_MODEL"

    # Embeddings
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768

    # Local fallback embedding service (local_embed/server.py, Qwen3-Embedding-0.6B).
    # Empty URL = fallback disabled. Vectors live in curriculum_chunks.embedding_local,
    # a separate space from `embedding` (Gemini): the two are never mixed.
    embedding_local_url: str = ""
    embedding_local_model: str = "Qwen/Qwen3-Embedding-0.6B"

    # Minimum cosine similarity for a retrieved chunk, per embedding space (scales differ
    # between models; calibrated with rag-experiment/kalibrasi_threshold.py).
    retrieval_threshold_gemini: float = 0.65
    retrieval_threshold_local: float = 0.55

    # Multi-AI Provider Keys
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
