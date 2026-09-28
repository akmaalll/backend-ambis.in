from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs

from app.models.base import Base


class Profile(AsyncAttrs, Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True)
    display_name = Column(Text, nullable=False)
    grade = Column(SmallInteger, server_default=text("7"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class Session(AsyncAttrs, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("mode in ('ask','learning_path','diagnostic')", name="sessions_mode_check"),
        CheckConstraint("status in ('active','ended')", name="sessions_status_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    student_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    mode = Column(Text, nullable=False)
    # Deferred FK in raw SQL (path_nodes doesn't exist yet when sessions is created
    # there) — no such ordering constraint in the ORM, so it's declared directly here.
    path_node_id = Column(UUID(as_uuid=True), ForeignKey("path_nodes.id", ondelete="SET NULL"), nullable=True)
    status = Column(Text, nullable=False, server_default=text("'active'"))
    started_at = Column(DateTime(timezone=True), server_default=text("now()"))
    ended_at = Column(DateTime(timezone=True), nullable=True)


class Message(AsyncAttrs, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role in ('student','agent','system')", name="messages_role_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class Problem(AsyncAttrs, Base):
    __tablename__ = "problems"
    __table_args__ = (
        CheckConstraint("source in ('exercise','ad_hoc')", name="problems_source_check"),
        CheckConstraint(
            "(source = 'exercise' and exercise_id is not null and problem_text is null) or "
            "(source = 'ad_hoc' and exercise_id is null and problem_text is not null)",
            name="problems_source_shape_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id"), nullable=False)
    source = Column(Text, nullable=False)
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("exercises.id"), nullable=True)
    problem_text = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class Attempt(AsyncAttrs, Base):
    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(
            "error_type in ('calculation','procedural','conceptual','prerequisite')",
            name="attempts_error_type_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    problem_id = Column(UUID(as_uuid=True), ForeignKey("problems.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id"), nullable=False)
    attempt_number = Column(SmallInteger, nullable=False, server_default=text("1"))
    student_answer = Column(Text, nullable=True)
    is_correct = Column(Boolean, nullable=True)
    error_type = Column(Text, nullable=True)
    detected_misconception_id = Column(UUID(as_uuid=True), ForeignKey("misconceptions.id"), nullable=True)
    hints_used = Column(SmallInteger, nullable=False, server_default=text("0"))
    time_spent_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class Intervention(AsyncAttrs, Base):
    __tablename__ = "interventions"
    __table_args__ = (
        CheckConstraint(
            "kind in ('hint','guiding_question','explanation','worked_example',"
            "'easier_exercise','prerequisite_review','difficulty_up')",
            name="interventions_kind_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id"), nullable=False)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("attempts.id"), nullable=True)
    kind = Column(Text, nullable=False)
    rule_code = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    content = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class StudentConceptState(AsyncAttrs, Base):
    __tablename__ = "student_concept_state"
    __table_args__ = (PrimaryKeyConstraint("student_id", "concept_id"),)

    student_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    concept_id = Column(UUID(as_uuid=True), ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    mastery = Column(Float, nullable=False, server_default=text("0"))
    confidence = Column(Float, nullable=False, server_default=text("0"))
    total_attempts = Column(Integer, nullable=False, server_default=text("0"))
    correct_streak = Column(Integer, nullable=False, server_default=text("0"))
    misconception_counts = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
