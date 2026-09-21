from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class LearningPathCreate(BaseModel):
    student_id: UUID
    subject_id: UUID
    target_concept_id: UUID
    # Advisory only — never overrides mastery from student_concept_state (see architecture decision).
    difficulty_preference: Optional[int] = Field(None, ge=1, le=5)
    goal_text: Optional[str] = None


class LearningPathResponse(BaseModel):
    id: UUID
    student_id: UUID
    subject_id: UUID
    target_concept_id: UUID
    difficulty_preference: Optional[int] = None
    goal_text: Optional[str] = None
    status: str
    diagnostic_session_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}
