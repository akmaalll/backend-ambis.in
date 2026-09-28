from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.schemas.curriculum import (
    ConceptResponse,
    ExerciseResponse,
    SubjectResponse,
    UnitResponse,
)
from app.api.v1.services.curriculum import CurriculumService

router = APIRouter(prefix="/curriculum", tags=["Curriculum"])


@router.get("/subjects", response_model=list[SubjectResponse], summary="List all subjects")
async def list_subjects(db: AsyncSession = Depends(get_db)):
    """Fetch all available curriculum subjects (e.g. Matematika, Informatika)."""
    service = CurriculumService(db)
    return await service.list_subjects()


@router.get(
    "/subjects/{subject_id}/units",
    response_model=list[UnitResponse],
    summary="List units in a subject",
)
async def list_units_by_subject(subject_id: UUID, db: AsyncSession = Depends(get_db)):
    """Fetch all instructional units belonging to a specific subject."""
    service = CurriculumService(db)
    subject = await service.get_subject(subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with id '{subject_id}' not found",
        )
    return await service.list_units_by_subject(subject_id)


@router.get(
    "/units/{unit_id}/concepts",
    response_model=list[ConceptResponse],
    summary="List concepts in a unit",
)
async def list_concepts_by_unit(unit_id: UUID, db: AsyncSession = Depends(get_db)):
    """Fetch all fine-grained concepts/modules belonging to a specific unit."""
    service = CurriculumService(db)
    unit = await service.get_unit(unit_id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unit with id '{unit_id}' not found",
        )
    return await service.list_concepts_by_unit(unit_id)


@router.get(
    "/concepts/{concept_id}",
    response_model=ConceptResponse,
    summary="Get details of a single concept",
)
async def get_concept(concept_id: UUID, db: AsyncSession = Depends(get_db)):
    """Fetch metadata and definition for a single concept."""
    service = CurriculumService(db)
    concept = await service.get_concept(concept_id)
    if not concept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Concept with id '{concept_id}' not found",
        )
    return concept


@router.get(
    "/concepts/{concept_id}/exercises",
    response_model=list[ExerciseResponse],
    summary="List exercises for a concept",
)
async def list_exercises_by_concept(
    concept_id: UUID,
    is_diagnostic: Optional[bool] = Query(
        None, description="Filter for diagnostic vs non-diagnostic practice exercises"
    ),
    difficulty: Optional[int] = Query(
        None, ge=1, le=5, description="Filter by difficulty level (1-5)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Fetch all diagnostic or practice exercises mapped to a concept."""
    service = CurriculumService(db)
    concept = await service.get_concept(concept_id)
    if not concept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Concept with id '{concept_id}' not found",
        )
    return await service.list_exercises_by_concept(
        concept_id=concept_id,
        is_diagnostic=is_diagnostic,
        difficulty=difficulty,
    )


@router.get(
    "/exercises/{exercise_id}",
    response_model=ExerciseResponse,
    summary="Get single exercise item",
)
async def get_exercise(exercise_id: UUID, db: AsyncSession = Depends(get_db)):
    """Fetch a single exercise item by ID."""
    service = CurriculumService(db)
    exercise = await service.get_exercise(exercise_id)
    if not exercise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exercise with id '{exercise_id}' not found",
        )
    return exercise
