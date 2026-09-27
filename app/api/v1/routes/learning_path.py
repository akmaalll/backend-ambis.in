from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.schemas.learning_path import (
    GenerateRoadmapRequest,
    GenerateRoadmapResponse,
    LearningPathCreate,
    LearningPathResponse,
    LessonIntroRequest,
    LessonIntroResponse,
)
from app.api.v1.services.learning_path import LearningPathService

router = APIRouter(prefix="/learning-paths", tags=["Learning Paths"])


@router.post("/", response_model=LearningPathResponse)
async def create_learning_path(data: LearningPathCreate, db: AsyncSession = Depends(get_db)):
    service = LearningPathService(db)
    return await service.create(data)


@router.get("/", response_model=list[LearningPathResponse])
async def list_learning_paths(db: AsyncSession = Depends(get_db)):
    service = LearningPathService(db)
    return await service.list_all()


@router.get("/{path_id}", response_model=LearningPathResponse)
async def get_learning_path(path_id: UUID, db: AsyncSession = Depends(get_db)):
    service = LearningPathService(db)
    result = await service.get_by_id(path_id)
    if not result:
        raise HTTPException(status_code=404, detail="Learning path not found")
    return result


@router.post("/generate-roadmap", response_model=GenerateRoadmapResponse, summary="Generate personalized AI roadmap")
async def generate_dynamic_roadmap(data: GenerateRoadmapRequest, db: AsyncSession = Depends(get_db)):
    """Generate a dynamic, personalized learning roadmap based on student's goal, level, and diagnostic assessment."""
    service = LearningPathService(db)
    return await service.generate_roadmap(data)


@router.post("/lesson-intro", response_model=LessonIntroResponse, summary="Generate proactive AI lesson kick-off")
async def generate_proactive_lesson_intro(data: LessonIntroRequest, db: AsyncSession = Depends(get_db)):
    """Generate a proactive opening greeting, analogy explanation, and interactive prompt chips for a milestone."""
    service = LearningPathService(db)
    return await service.generate_lesson_intro(data)
