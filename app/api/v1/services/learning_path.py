from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.learning_path import LearningPathCreate
from app.models.learning_path import LearningPath


class LearningPathService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: LearningPathCreate) -> LearningPath:
        model = LearningPath(**data.model_dump())
        self.db.add(model)
        await self.db.commit()
        await self.db.refresh(model)
        return model

    async def list_all(self) -> list[LearningPath]:
        result = await self.db.execute(select(LearningPath).order_by(LearningPath.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_id(self, path_id: UUID) -> LearningPath | None:
        result = await self.db.execute(select(LearningPath).where(LearningPath.id == path_id))
        return result.scalar_one_or_none()
