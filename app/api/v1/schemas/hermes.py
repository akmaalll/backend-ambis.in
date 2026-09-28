from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class HermesAgentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    student_id: UUID = Field(
        default=UUID("00000000-0000-0000-0000-000000000901"),
        validation_alias=AliasChoices("student_id", "user_id"),
    )
    student_answer: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        validation_alias=AliasChoices("student_answer", "prompt"),
    )
    session_id: UUID | None = None
    problem_id: UUID | None = None
    exercise_id: UUID | None = Field(
        default=UUID("00000000-0000-0000-0000-000000000401"),
    )
    mode: str = Field(default="ask", pattern="^(ask|learning_path|diagnostic|productivity_task)$")
    time_spent_ms: int | None = None
    stream: bool = True

    @model_validator(mode="after")
    def _require_exercise_or_problem(self):
        if self.problem_id is None and self.exercise_id is None:
            self.exercise_id = UUID("00000000-0000-0000-0000-000000000401")
        return self


class HermesAgentSSEEvent(BaseModel):
    event: str = "token"
    data: dict[str, Any] = Field(default_factory=dict)


class InterventionPayload(BaseModel):
    kind: str
    rule_code: str
    reason: str
    text: str


class HermesNonStreamResponse(BaseModel):
    session_id: UUID
    problem_id: UUID
    attempt_id: UUID
    attempt_number: int
    is_correct: bool
    error_type: str | None
    misconception_code: str | None
    intervention: InterventionPayload | None  # None iff the attempt was correct — no scaffolding needed
    mastery: float
    confidence: float
    processing_time_ms: int
