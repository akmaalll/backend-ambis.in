from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncAttrs

from app.models.base import Base


class LearningPath(AsyncAttrs, Base):
    __tablename__ = "learning_paths"
    __table_args__ = (
        CheckConstraint("difficulty_preference between 1 and 5", name="learning_paths_difficulty_preference_check"),
        CheckConstraint("status in ('active','completed','abandoned')", name="learning_paths_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("subjects.id"), nullable=False)
    # Dipilih eksplisit dari modal (topik=unit, sub materi=concept), bukan hasil
    # parsing LLM/NLU — lihat AMBIS_DB_Architecture.md keputusan 10.
    target_concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id"), nullable=False)
    # Self-reported, ADVISORY ONLY — tidak pernah override mastery hasil diagnostic.
    difficulty_preference = Column(SmallInteger, nullable=True)
    goal_text = Column(Text, nullable=True)
    status = Column(Text, nullable=False, server_default=text("'active'"))
    diagnostic_session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class PathNode(AsyncAttrs, Base):
    __tablename__ = "path_nodes"
    __table_args__ = (
        CheckConstraint(
            "node_type in ('lesson','practice','checkpoint','remediation')",
            name="path_nodes_node_type_check",
        ),
        CheckConstraint(
            "status in ('locked','available','in_progress','done','skipped')",
            name="path_nodes_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    path_id = Column(UUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False)
    # Gap numbering: seed 100/200/300/... so inserts (e.g. remediation) use a
    # midpoint value (150) instead of cascading a renumber.
    position = Column(Integer, nullable=False)
    node_type = Column(Text, nullable=False)
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id"), nullable=False)
    status = Column(Text, nullable=False, server_default=text("'locked'"))
    adaptation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
