from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.schemas.learning_path import LearningPathCreate, LearningPathResponse
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
