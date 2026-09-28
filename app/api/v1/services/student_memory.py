"""Student memory service — persistent cross-session memory in PostgreSQL DB."""
import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_STUDENT_ID = "00000000-0000-0000-0000-000000000901"

# Heuristic patterns to detect student introductions in Indonesian
NAME_PATTERNS = [
    # "Halo kak, nama aku Budi", "namaku Siti Aminah", "nama saya Reno"
    re.compile(
        r"(?:(?:halo|hai|pagi|siang|sore|malam)\s*(?:kak|om|bang|bu|pak)?\s*,?\s*)?"
        r"(?:kenalin\s+)?(?:nama\s+(?:saya|aku|ku)|namaku)\s*(?:adalah\s*)?([A-Za-z][A-Za-z0-9_\s]{1,30})",
        re.IGNORECASE,
    ),
    # "panggil aku Daffa", "panggil saja Rian"
    re.compile(
        r"(?:panggil\s+(?:aku|saja|gue|gw))\s+([A-Za-z][A-Za-z0-9_\s]{1,25})",
        re.IGNORECASE,
    ),
    # "aku Budi, siswa kelas 7", "aku Budi dari SMP..."
    re.compile(
        r"(?:halo|hai)?\s*(?:kak\s*,?\s*)?(?:aku|saya|gue)\s+([A-Z][a-z]{1,18})"
        r"(?:\s*,\s*(?:siswa|anak|kelas|murid)|\s+(?:dari|anak|siswa))",
        re.IGNORECASE,
    ),
]

GRADE_PATTERNS = [
    re.compile(r"kelas\s*([0-9]{1,2}|VII|VIII|IX|X|XI|XII|smp|sma)", re.IGNORECASE),
]


class StudentMemoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_schema(self) -> None:
        """Create student_memories table if not exists (safe idempotent migration)."""
        create_sql = text(
            """
            CREATE TABLE IF NOT EXISTS student_memories (
                student_id UUID PRIMARY KEY,
                name TEXT,
                grade TEXT,
                goal TEXT,
                topic TEXT,
                facts JSONB DEFAULT '[]'::jsonb,
                summary TEXT,
                updated_at TIMESTAMPTZ DEFAULT now()
            );
            """
        )
        try:
            await self.db.execute(create_sql)
            await self.db.commit()
        except Exception as exc:
            logger.warning("ensure_schema student_memories warning: %s", exc)
            await self.db.rollback()

    async def get_memory(self, student_id: str) -> dict[str, Any]:
        """Fetch persistent student memory from DB."""
        await self.ensure_schema()
        valid_id = self._safe_uuid(student_id)
        query = text(
            """
            SELECT student_id, name, grade, goal, topic, facts, summary, updated_at
            FROM student_memories
            WHERE student_id = :student_id::uuid
            """
        )
        try:
            res = await self.db.execute(query, {"student_id": valid_id})
            row = res.mappings().first()
            if row:
                facts = row.get("facts")
                if isinstance(facts, str):
                    try:
                        facts = json.loads(facts)
                    except Exception:
                        facts = []
                stored_name = row["name"]
                if stored_name and not self._is_valid_name(stored_name):
                    stored_name = None

                return {
                    "student_id": str(row["student_id"]),
                    "name": stored_name,
                    "grade": row["grade"],
                    "goal": row["goal"],
                    "topic": row["topic"],
                    "facts": facts or [],
                    "summary": row["summary"],
                    "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
                }
        except Exception as exc:
            logger.warning("Error fetching student memory from DB: %s", exc)

        # Fallback to profiles table if present
        try:
            prof_query = text(
                "SELECT id, display_name, grade FROM profiles WHERE id = :id::uuid"
            )
            res = await self.db.execute(prof_query, {"id": valid_id})
            prow = res.mappings().first()
            if prow:
                dname = prow.get("display_name")
                name = dname if (dname and self._is_valid_name(dname)) else None
                return {
                    "student_id": str(prow["id"]),
                    "name": name,
                    "grade": f"Kelas {prow.get('grade')}" if prow.get("grade") else None,
                    "goal": None,
                    "topic": None,
                    "facts": [],
                    "summary": None,
                    "updated_at": None,
                }
        except Exception as exc:
            logger.debug("Fallback profile lookup skipped: %s", exc)

        return {
            "student_id": valid_id,
            "name": None,
            "grade": None,
            "goal": None,
            "topic": None,
            "facts": [],
            "summary": None,
            "updated_at": None,
        }

    async def save_memory(
        self,
        student_id: str,
        name: str | None = None,
        grade: str | None = None,
        goal: str | None = None,
        topic: str | None = None,
        facts: list[str] | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Save or update student memory into PostgreSQL."""
        await self.ensure_schema()
        valid_id = self._safe_uuid(student_id)
        # Clean up name if provided
        clean_name = self._sanitize_name(name) if name else None

        existing = await self.get_memory(valid_id)
        # Do not overwrite a valid existing name with None unless explicitly provided
        final_name = clean_name or existing.get("name")
        if final_name and not self._is_valid_name(final_name):
            final_name = None

        final_grade = grade or existing.get("grade")
        final_goal = goal or existing.get("goal")
        final_topic = topic or existing.get("topic")
        final_summary = summary or existing.get("summary")

        # Merge facts list
        merged_facts = list(existing.get("facts") or [])
        if facts:
            for f in facts:
                if f and f not in merged_facts and "siapa" not in f.lower():
                    merged_facts.append(f)

        upsert_sql = text(
            """
            INSERT INTO student_memories (student_id, name, grade, goal, topic, facts, summary, updated_at)
            VALUES (:student_id::uuid, :name, :grade, :goal, :topic, :facts::jsonb, :summary, now())
            ON CONFLICT (student_id) DO UPDATE SET
                name = COALESCE(:name, student_memories.name),
                grade = COALESCE(:grade, student_memories.grade),
                goal = COALESCE(:goal, student_memories.goal),
                topic = COALESCE(:topic, student_memories.topic),
                facts = :facts::jsonb,
                summary = COALESCE(:summary, student_memories.summary),
                updated_at = now()
            """
        )

        try:
            await self.db.execute(
                upsert_sql,
                {
                    "student_id": valid_id,
                    "name": final_name,
                    "grade": final_grade,
                    "goal": final_goal,
                    "topic": final_topic,
                    "facts": json.dumps(merged_facts),
                    "summary": final_summary,
                },
            )
            # Sync display_name in profiles if table exists
            if final_name:
                try:
                    sync_prof = text(
                        "UPDATE profiles SET display_name = :name WHERE id = :student_id::uuid"
                    )
                    await self.db.execute(
                        sync_prof, {"name": final_name, "student_id": valid_id}
                    )
                except Exception as p_err:
                    logger.debug("Sync to profiles table skipped: %s", p_err)

            await self.db.commit()
        except Exception as exc:
            logger.warning("Error saving student memory to DB: %s", exc)
            await self.db.rollback()

        return {
            "student_id": valid_id,
            "name": final_name,
            "grade": final_grade,
            "goal": final_goal,
            "topic": final_topic,
            "facts": merged_facts,
            "summary": final_summary,
        }

    @staticmethod
    def _safe_uuid(raw_id: str | None) -> str:
        if not raw_id:
            return DEFAULT_STUDENT_ID
        try:
            return str(UUID(str(raw_id)))
        except (ValueError, AttributeError):
            return DEFAULT_STUDENT_ID

    @classmethod
    def extract_identity_from_text(cls, text: str) -> dict[str, Any]:
        """Detect if the user is introducing their name or grade.
        NEVER extract a name if the sentence is a question (e.g. 'namaku siapa?', 'siapa namaku?').
        """
        # If the text is asking a question about identity, DO NOT extract a name!
        if cls.is_question_about_name(text):
            return {}

        result: dict[str, Any] = {}
        for pattern in NAME_PATTERNS:
            match = pattern.search(text)
            if match:
                raw_name = match.group(1).strip()
                cleaned = cls._sanitize_name(raw_name)
                if cleaned and cls._is_valid_name(cleaned):
                    result["name"] = cleaned
                    break

        for pattern in GRADE_PATTERNS:
            gmatch = pattern.search(text)
            if gmatch:
                gval = gmatch.group(1).strip()
                result["grade"] = f"Kelas {gval}"
                break

        return result

    @classmethod
    def is_question_about_name(cls, text: str) -> bool:
        """Check if message is asking a question testing name memory rather than introducing."""
        t = text.lower().strip()
        # If there's a question mark and words related to identity/knowing/remembering
        if "?" in t:
            return True
        question_words = ["siapa", "siapakah", "apakah", "ingat", "tau", "tahu", "lupa", "tebak"]
        for qw in question_words:
            if qw in t.split():
                return True
        return False

    @classmethod
    def _is_valid_name(cls, name: str | None) -> bool:
        if not name:
            return False
        cleaned = re.sub(r"[.,!?;:]", "", name).strip().lower()
        disallowed = {
            "siapa", "siapakah", "apa", "apakah", "mana", "dimana", "kenapa", "mengapa",
            "kamu", "anda", "engkau", "kau", "dia", "mereka", "kita", "kami",
            "aku", "saya", "gue", "gw", "lu", "lo", "kakak", "kak", "om", "tante",
            "tutor", "guru", "siswa", "murid", "pelajar", "teman",
            "tahu", "tau", "ingat", "lupa", "bukan", "tidak", "bisa", "mau",
            "siswa demo", "anonim", "user", "admin", "null", "undefined",
        }
        if cleaned in disallowed:
            return False
        # If any word inside is a question word
        for bad in {"siapa", "siapakah", "apakah", "tahu", "tau", "ingat", "lupa"}:
            if bad in cleaned.split():
                return False
        return len(cleaned) >= 2

    @classmethod
    def _sanitize_name(cls, name: str | None) -> str | None:
        if not name:
            return None
        # Remove trailing punctuation or conversational filler
        cleaned = re.sub(r"[.,!?;:]", "", name).strip()
        if not cls._is_valid_name(cleaned):
            return None
        stop_words = {
            "ya", "nih", "dong", "sih", "kak", "om", "halo", "hai",
            "siswa", "murid", "pelajar", "seorang", "baru", "belajar",
        }
        words = [w for w in cleaned.split() if w.lower() not in stop_words]
        if not words or len(" ".join(words)) < 2:
            return None
        sanitized = " ".join(w.capitalize() for w in words[:4])
        return sanitized if cls._is_valid_name(sanitized) else None
