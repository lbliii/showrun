"""Task questions and demonstrated answers (#17, epic #6)."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

import pytest
from chirp.testing import TestClient

from showrun.community import CommunityStore, validate_card
from showrun.questions import QuestionError, QuestionsStore, validate_question_title
from showrun.store import ShowrunStore
from showrun.web import create_app
from tests.test_community_web import (
    _csrf,
    _publish_public_release,
    _publish_technique,
    _signup,
    _updated_cookie,
)


def _application(database: Path):
    return create_app(
        f"sqlite:///{database}",
        secret_key="test-signing-key-with-enough-entropy",
    )


async def _creator_with_technique(store, community, *, email, name):
    user = await store.create_user(email=email, name=name, password_hash="test-only-hash")
    profile = await community.ensure_profile(
        user_id=user.id, workspace_id=user.workspace_id, display_name=name, email=email
    )
    golden = await store.get_lesson("lesson_golden")
    draft = await store.create_draft(
        replace(golden.artifact, title=f"{name} technique"), workspace_id=user.workspace_id
    )
    release = await store.publish(draft.id, "public", workspace_id=user.workspace_id)
    technique, _v, _c = await community.publish_technique_version(
        user_id=user.id,
        workspace_id=user.workspace_id,
        display_name=name,
        email=email,
        release_slug=release.slug,
        card=validate_card(
            problem="p",
            pattern="pattern text",
            use_when="when",
            objective="obj",
            summary="s",
            topics=("reliability",),
        ),
    )
    return user, profile, technique, release


def test_question_validation() -> None:
    with pytest.raises(QuestionError):
        validate_question_title("too short")
    assert validate_question_title("How do I retry a flaky tool safely?").startswith("How")


async def test_ask_answer_accept_exactly_one(tmp_path: Path) -> None:
    app = _application(tmp_path / "questions.db")
    async with TestClient(app):
        store = ShowrunStore(app.db)
        community = CommunityStore(app.db)
        questions = QuestionsStore(app.db)

        asker = await store.create_user(
            email="asker@example.com", name="Asker", password_hash="test-only-hash"
        )
        asker_profile = await community.ensure_profile(
            user_id=asker.id,
            workspace_id=asker.workspace_id,
            display_name="Asker",
            email=asker.email,
        )
        _u1, _p1, tech1, rel1 = await _creator_with_technique(
            store, community, email="a1@example.com", name="Answerer One"
        )
        _u2, p2, tech2, _rel2 = await _creator_with_technique(
            store, community, email="a2@example.com", name="Answerer Two"
        )

        question = await questions.ask_question(
            asker_profile_id=asker_profile.id,
            workspace_id=asker.workspace_id,
            title="How do I make an agent retry a flaky tool safely?",
            body="Context here.",
            topics=("reliability",),
        )
        # Ungoverned topic rejected.
        with pytest.raises(QuestionError):
            await questions.ask_question(
                asker_profile_id=asker_profile.id,
                workspace_id=asker.workspace_id,
                title="A totally valid question title here",
                body="",
                topics=("not-a-real-topic",),
            )

        _q, ans1 = await questions.answer_question(
            answerer_profile_id=(await community.get_profile_by_user(_u1.id)).id,
            workspace_id=_u1.workspace_id,
            question_slug=question.slug,
            technique_slug=tech1.slug,
        )
        _q, ans2 = await questions.answer_question(
            answerer_profile_id=p2.id,
            workspace_id=_u2.workspace_id,
            question_slug=question.slug,
            technique_slug=tech2.slug,
        )
        assert len(await questions.list_answers(question.id)) == 2

        # Only the asker can accept.
        with pytest.raises(PermissionError):
            await questions.accept_answer(
                asker_workspace_id=_u1.workspace_id,
                question_slug=question.slug,
                answer_id=ans1,
            )

        await questions.accept_answer(
            asker_workspace_id=asker.workspace_id, question_slug=question.slug, answer_id=ans1
        )
        accepted = {a.id for a in await questions.list_answers(question.id) if a.accepted}
        assert accepted == {ans1}

        # Accepting a different answer replaces it — still exactly one.
        await questions.accept_answer(
            asker_workspace_id=asker.workspace_id, question_slug=question.slug, answer_id=ans2
        )
        accepted = {a.id for a in await questions.list_answers(question.id) if a.accepted}
        assert accepted == {ans2}

        # An answer becomes ineligible when its backing release is unavailable.
        await store.unpublish_release(rel1.slug, workspace_id=_u1.workspace_id)
        remaining = {a.id for a in await questions.list_answers(question.id)}
        assert ans1 not in remaining and ans2 in remaining


async def test_ask_answer_accept_over_http(tmp_path: Path) -> None:
    app = _application(tmp_path / "questions-web.db")
    async with TestClient(app) as client:
        cookie = await _signup(client, email="creator@example.com", name="Ada Creator")
        lesson_path, cookie = await _publish_public_release(client, cookie, title="Retry pattern")
        technique_path, cookie = await _publish_technique(client, cookie, lesson_path)
        technique_slug = technique_path.rsplit("/", 1)[-1]

        ask = await client.get("/questions/ask", headers={"Cookie": cookie})
        cookie = _updated_cookie(ask, cookie)
        posted = await client.post(
            "/questions",
            body=urlencode(
                {
                    "title": "How do I retry a flaky tool safely with an agent?",
                    "body": "",
                    "topics": "reliability",
                    "_csrf_token": _csrf(ask.text),
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert posted.status == 303
        q_path = posted.header("location")

        detail = await client.get(q_path, headers={"Cookie": cookie})
        cookie = _updated_cookie(detail, cookie)
        answered = await client.post(
            f"{q_path}/answers",
            body=urlencode(
                {"technique_slug": technique_slug, "_csrf_token": _csrf(detail.text)}
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert answered.status == 303

        detail = await client.get(q_path, headers={"Cookie": cookie})
        cookie = _updated_cookie(detail, cookie)
        accept_match = re.search(r"/questions/[^/]+/accept/(answer_[a-f0-9]+)", detail.text)
        assert accept_match is not None
        accept = await client.post(
            accept_match.group(0),
            body=urlencode({"_csrf_token": _csrf(detail.text)}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie},
        )
        assert accept.status == 303

        final = await client.get(q_path)
        assert final.status == 200
        assert "accepted" in final.text
