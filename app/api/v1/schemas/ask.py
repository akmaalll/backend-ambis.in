from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.services.multi_ai import DEFAULT_MODEL_ID


class AskRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    question: str = Field(..., min_length=1, max_length=5000)
    context: str = Field(default="", max_length=10000)
    mode: str = Field(default="general", pattern="^(general|learning_path|code)$")
    model_id: str = Field(
        default=DEFAULT_MODEL_ID,
        description="ID model AI yang dipakai, misal: groq/llama-3.3-70b-versatile",
    )


class AskResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    answer: str
    references: list[str] = []
    processing_time_ms: int
    mode_used: str
    model_used: str = DEFAULT_MODEL_ID
