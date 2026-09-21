from typing import Optional, Sequence, Type, TypeVar
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base
from app.models.curriculum import Subject, Unit, Concept, Exercise

T = TypeVar("T", bound=Base)


class CurriculumService:
    """Read-only service for navigating the curriculum graph and exercise items."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_by_id(self, model_cls: Type[T], entity_id: UUID) -> Optional[T]:
        """Generic reusable helper to fetch a model by primary key."""
        stmt = select(model_cls).where(model_cls.id == entity_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_subjects(self) -> Sequence[Subject]:
        stmt = select(Subject).order_by(Subject.name.asc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_subject(self, subject_id: UUID) -> Optional[Subject]:
        return await self._get_by_id(Subject, subject_id)

    async def list_units_by_subject(self, subject_id: UUID) -> Sequence[Unit]:
        stmt = select(Unit).where(Unit.subject_id == subject_id).order_by(Unit.position.asc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_unit(self, unit_id: UUID) -> Optional[Unit]:
        return await self._get_by_id(Unit, unit_id)

    async def list_concepts_by_unit(self, unit_id: UUID) -> Sequence[Concept]:
        stmt = select(Concept).where(Concept.unit_id == unit_id).order_by(Concept.position.asc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_concept(self, concept_id: UUID) -> Optional[Concept]:
        return await self._get_by_id(Concept, concept_id)

    async def list_exercises_by_concept(
        self,
        concept_id: UUID,
        is_diagnostic: Optional[bool] = None,
        difficulty: Optional[int] = None,
    ) -> Sequence[Exercise]:
        stmt = select(Exercise).where(Exercise.concept_id == concept_id)
        if is_diagnostic is not None:
            stmt = stmt.where(Exercise.is_diagnostic == is_diagnostic)
        if difficulty is not None:
            stmt = stmt.where(Exercise.difficulty == difficulty)
        stmt = stmt.order_by(Exercise.difficulty.asc(), Exercise.is_diagnostic.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_exercise(self, exercise_id: UUID) -> Optional[Exercise]:
        return await self._get_by_id(Exercise, exercise_id)
