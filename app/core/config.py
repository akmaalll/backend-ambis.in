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

    # Legacy LLM proxy (9router) - kept for embeddings only
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model_grading: str = "cc/PLACEHOLDER_MODEL"
    llm_model_diagnosis: str = "cc/PLACEHOLDER_MODEL"
    llm_model_intervention: str = "cc/PLACEHOLDER_MODEL"

    # Embeddings
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768

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
