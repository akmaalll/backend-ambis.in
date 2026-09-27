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


class GenerateRoadmapRequest(BaseModel):
    topic: str = "Matematika"
    subtopic: str = "Pecahan"
    goal: Optional[str] = None
    difficulty: Optional[str] = "beginner"
    diagnostic_score: Optional[float] = None
    misconceptions: Optional[list[str]] = None


class RoadmapStepSchema(BaseModel):
    id: str
    title: str
    description: str
    type: str = "lesson"  # lesson, practice, checkpoint
    recommended_badge: Optional[str] = None
    has_quiz: bool = False


class GenerateRoadmapResponse(BaseModel):
    title: str
    reasoning: str
    steps: list[RoadmapStepSchema]
    is_fallback: bool = False
    message: Optional[str] = None


class LessonIntroRequest(BaseModel):
    step_title: str
    step_description: str
    topic: str = "Matematika"
    subtopic: str = "Pecahan"
    student_name: Optional[str] = "Siswa"


class LessonIntroResponse(BaseModel):
    greeting: str
    content: str
    quick_prompts: list[str]
    is_fallback: bool = False
    message: Optional[str] = None
