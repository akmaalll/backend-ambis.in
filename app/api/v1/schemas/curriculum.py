from typing import Any, Optional
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CurriculumBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SubjectResponse(CurriculumBaseSchema):
    id: UUID
    code: str
    name: str


class UnitResponse(CurriculumBaseSchema):
    id: UUID
    subject_id: UUID
    name: str
    position: int = 0


class ConceptResponse(CurriculumBaseSchema):
    id: UUID
    unit_id: UUID
    code: str
    name: str
    description: Optional[str] = None
    position: int = 0


class ExerciseResponse(CurriculumBaseSchema):
    id: UUID
    concept_id: UUID
    difficulty: int = Field(..., ge=1, le=5)
    kind: str
    is_diagnostic: bool
    question: str
    options: Optional[Any] = None
    correct_answer: str
    solution_steps: Optional[Any] = None
    # AliasChoices with metadata_ first ensures SQLAlchemy ORM's metadata_ is chosen over MetaData()
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
        serialization_alias="metadata",
    )
