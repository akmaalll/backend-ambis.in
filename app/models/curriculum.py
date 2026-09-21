from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs

from app.models.base import Base


class Subject(AsyncAttrs, Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("code", name="subjects_code_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)


class Unit(AsyncAttrs, Base):
    __tablename__ = "units"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, server_default=text("0"))


class Concept(AsyncAttrs, Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("code", name="concepts_code_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    unit_id = Column(UUID(as_uuid=True), ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, server_default=text("0"))


class ConceptPrerequisite(AsyncAttrs, Base):
    __tablename__ = "concept_prerequisites"
    __table_args__ = (
        PrimaryKeyConstraint("concept_id", "prerequisite_id"),
        CheckConstraint("concept_id <> prerequisite_id", name="concept_prerequisites_check"),
    )

    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    prerequisite_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)


class Misconception(AsyncAttrs, Base):
    __tablename__ = "misconceptions"
    __table_args__ = (UniqueConstraint("code", name="misconceptions_code_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    code = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    remediation_hint = Column(Text, nullable=True)


class Exercise(AsyncAttrs, Base):
    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint("difficulty between 1 and 5", name="exercises_difficulty_check"),
        CheckConstraint("kind in ('mcq','short_answer','steps')", name="exercises_kind_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    difficulty = Column(SmallInteger, nullable=False)
    kind = Column(Text, nullable=False)
    is_diagnostic = Column(Boolean, nullable=False, server_default=text("false"))
    question = Column(Text, nullable=False)
    # mcq: [{key,label,misconception_id|null}]
    options = Column(JSONB, nullable=True)
    correct_answer = Column(Text, nullable=False)
    solution_steps = Column(JSONB, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class CurriculumChunk(AsyncAttrs, Base):
    __tablename__ = "curriculum_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    # `embedding vector(768)` intentionally not mapped here — pgvector ORM support
    # is deferred (see plan decision 3); the column + HNSW index still exist at the
    # DB level via the raw-SQL migration.
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
