"""Task questions and demonstrated answers.

A question is public task framing. An answer references a *published technique*
(a demonstrated answer), never free text, and only surfaces while that
technique stays publicly eligible. The asker may accept exactly one answer.
Answer eligibility reuses the community `public_eligibility_sql` contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from showrun.community import public_eligibility_sql, topic_key


class QuestionError(ValueError):
    """Raised when question/answer input fails validation."""


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    id: str
    asker_profile_id: str
    workspace_id: str
    slug: str
    title: str
    body: str
    accepted_answer_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class QuestionCard:
    id: str
    slug: str
    title: str
    asker_handle: str
    created_at: str
    answer_count: int
    accepted: bool


@dataclass(frozen=True, slots=True)
class AnswerView:
    id: str
    question_id: str
    technique_id: str
    technique_slug: str
    technique_title: str
    answerer_handle: str
    is_accepted: int

    @property
    def accepted(self) -> bool:
        return bool(self.is_accepted)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "question"
    return f"{base}-{uuid4().hex[:7]}"


def validate_question_title(value: str) -> str:
    title = " ".join(str(value or "").split())
    if not title:
        raise QuestionError("Frame the task as a clear question.")
    if len(title) < 12:
        raise QuestionError("Give the question enough task framing (at least 12 characters).")
    if len(title) > 160:
        raise QuestionError("Keep the question title to 160 characters or fewer.")
    return title


def validate_question_body(value: str) -> str:
    body = " ".join(str(value or "").split())
    if len(body) > 2000:
        raise QuestionError("Keep the details to 2000 characters or fewer.")
    return body


def normalize_topics(raw: Any) -> tuple[str, ...]:
    values = re.split(r"[,\n]", raw) if isinstance(raw, str) else list(raw or ())
    keys: list[str] = []
    for candidate in values:
        key = topic_key(str(candidate))
        if key and key not in keys:
            keys.append(key)
    if not keys:
        raise QuestionError("Add at least one topic.")
    if len(keys) > 5:
        raise QuestionError("Use five topics or fewer.")
    return tuple(keys)


# Eligible-answer subquery: an answer surfaces only while its technique is a
# public, discoverable head version (same contract as discovery).
_ANSWER_ELIGIBLE = (
    "EXISTS (SELECT 1 FROM techniques t "
    "JOIN profiles p ON p.id = t.profile_id "
    "JOIN technique_versions tv ON tv.technique_id = t.id "
    "JOIN releases r ON r.id = tv.release_id "
    f"WHERE t.id = a.technique_id AND {public_eligibility_sql(discoverable=True)})"
)


class QuestionsStore:
    """Persistence for questions and demonstrated answers."""

    def __init__(self, database: Any) -> None:
        self.db = database

    async def _resolve_topic_id(self, key: str) -> str:
        topic_id = await self.db.fetch_val("SELECT id FROM topics WHERE key = ?", key)
        if not topic_id:
            raise QuestionError(f"'{key}' is not a known topic. Choose topics from the catalog.")
        return str(topic_id)

    async def ask_question(
        self,
        *,
        asker_profile_id: str,
        workspace_id: str,
        title: str,
        body: str,
        topics: Any,
    ) -> QuestionRecord:
        clean_title = validate_question_title(title)
        clean_body = validate_question_body(body)
        keys = normalize_topics(topics)
        now = _now()
        question_id = f"question_{uuid4().hex}"
        async with self.db.transaction():
            topic_ids = [await self._resolve_topic_id(key) for key in keys]
            await self.db.execute(
                "INSERT INTO questions "
                "(id, asker_profile_id, workspace_id, slug, title, body, "
                "accepted_answer_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                question_id,
                asker_profile_id,
                workspace_id,
                _slugify(clean_title),
                clean_title,
                clean_body,
                now,
                now,
            )
            for topic_id in topic_ids:
                await self.db.execute(
                    "INSERT INTO question_topics (question_id, topic_id) "
                    "VALUES (?, ?) ON CONFLICT DO NOTHING",
                    question_id,
                    topic_id,
                )
        question = await self.get_question_by_id(question_id)
        if question is None:
            raise RuntimeError("Question was not persisted")
        return question

    async def get_question(self, slug: str) -> QuestionRecord | None:
        return await self.db.fetch_one(
            QuestionRecord,
            "SELECT id, asker_profile_id, workspace_id, slug, title, body, "
            "accepted_answer_id, created_at, updated_at FROM questions WHERE slug = ?",
            slug,
        )

    async def get_question_by_id(self, question_id: str) -> QuestionRecord | None:
        return await self.db.fetch_one(
            QuestionRecord,
            "SELECT id, asker_profile_id, workspace_id, slug, title, body, "
            "accepted_answer_id, created_at, updated_at FROM questions WHERE id = ?",
            question_id,
        )

    async def list_questions(self) -> list[QuestionCard]:
        questions = await self.db.fetch(
            _QuestionRow,
            "SELECT q.id, q.slug, q.title, p.handle AS asker_handle, q.created_at, "
            "q.accepted_answer_id "
            "FROM questions q JOIN profiles p ON p.id = q.asker_profile_id "
            "ORDER BY q.created_at DESC, q.id ASC",
        )
        cards: list[QuestionCard] = []
        for row in questions:
            count = await self.db.fetch_val(
                "SELECT COUNT(*) FROM answers a "
                f"WHERE a.question_id = ? AND {_ANSWER_ELIGIBLE}",
                row.id,
            )
            cards.append(
                QuestionCard(
                    id=row.id,
                    slug=row.slug,
                    title=row.title,
                    asker_handle=row.asker_handle,
                    created_at=row.created_at,
                    answer_count=int(count or 0),
                    accepted=row.accepted_answer_id is not None,
                )
            )
        return cards

    async def list_answers(self, question_id: str) -> list[AnswerView]:
        return await self.db.fetch(
            AnswerView,
            "SELECT a.id, a.question_id, a.technique_id, t.slug AS technique_slug, "
            "t.title AS technique_title, p.handle AS answerer_handle, "
            "CASE WHEN q.accepted_answer_id = a.id THEN 1 ELSE 0 END AS is_accepted "
            "FROM answers a "
            "JOIN questions q ON q.id = a.question_id "
            "JOIN profiles p ON p.id = a.answerer_profile_id "
            "JOIN techniques t ON t.id = a.technique_id "
            f"WHERE a.question_id = ? AND {_ANSWER_ELIGIBLE} "
            "ORDER BY is_accepted DESC, a.created_at ASC",
            question_id,
        )

    async def answer_question(
        self,
        *,
        answerer_profile_id: str,
        workspace_id: str,
        question_slug: str,
        technique_slug: str,
    ) -> tuple[QuestionRecord, str]:
        """Answer with an eligible technique. Returns (question, answer_id)."""

        async with self.db.transaction():
            question = await self.get_question(question_slug)
            if question is None:
                raise LookupError("Question not found")
            technique = await self.db.fetch_one(
                _TechniqueEligibleRow,
                "SELECT t.id "
                "FROM techniques t "
                "JOIN profiles p ON p.id = t.profile_id "
                "JOIN technique_versions tv ON tv.technique_id = t.id "
                "JOIN releases r ON r.id = tv.release_id "
                f"WHERE t.slug = ? AND {public_eligibility_sql(discoverable=True)} "
                "LIMIT 1",
                technique_slug,
            )
            if technique is None:
                raise QuestionError("Answer with a published, discoverable technique.")
            answer_id = f"answer_{uuid4().hex}"
            inserted = await self.db.execute(
                "INSERT INTO answers "
                "(id, question_id, technique_id, answerer_profile_id, workspace_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (question_id, technique_id) DO NOTHING",
                answer_id,
                question.id,
                technique.id,
                answerer_profile_id,
                workspace_id,
                _now(),
            )
            if not inserted:
                existing = await self.db.fetch_val(
                    "SELECT id FROM answers WHERE question_id = ? AND technique_id = ?",
                    question.id,
                    technique.id,
                )
                return question, str(existing)
            return question, answer_id

    async def accept_answer(
        self,
        *,
        asker_workspace_id: str,
        question_slug: str,
        answer_id: str,
    ) -> QuestionRecord:
        """Accept exactly one answer. Only the asker may accept."""

        async with self.db.transaction():
            question = await self.get_question(question_slug)
            if question is None:
                raise LookupError("Question not found")
            if question.workspace_id != asker_workspace_id:
                raise PermissionError("Only the asker can accept an answer.")
            owns = await self.db.fetch_val(
                "SELECT 1 FROM answers WHERE id = ? AND question_id = ?",
                answer_id,
                question.id,
            )
            if not owns:
                raise LookupError("Answer not found for this question.")
            await self.db.execute(
                "UPDATE questions SET accepted_answer_id = ?, updated_at = ? WHERE id = ?",
                answer_id,
                _now(),
                question.id,
            )
        updated = await self.get_question_by_id(question.id)
        if updated is None:
            raise RuntimeError("Acceptance was not persisted")
        return updated


@dataclass(frozen=True, slots=True)
class _QuestionRow:
    id: str
    slug: str
    title: str
    asker_handle: str
    created_at: str
    accepted_answer_id: str | None


@dataclass(frozen=True, slots=True)
class _TechniqueEligibleRow:
    id: str
