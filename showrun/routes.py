"""Command-oriented HTTP routes for the Showrun vertical slice."""

from __future__ import annotations

import hashlib
import html
import json
import os
from dataclasses import asdict, replace
from math import isfinite
from typing import Any
from urllib.parse import urlencode

from chirp.app import App
from chirp.data import QueryError
from chirp.http.forms import UploadFile
from chirp.http.request import Request
from chirp.http.response import Response
from chirp.middleware.auth import current_user, login, logout
from chirp.templating.returns import MutationResult, Page

from showrun.artifacts import (
    ShowrunArtifact,
    artifact_from_json,
    create_artifact_from_text,
    direct_artifact,
)
from showrun.auth import (
    LoginThrottle,
    issue_token,
    normalize_email,
    password_hash,
    validate_name,
    verify_password,
)
from showrun.community import (
    CommunityStore,
    ProfileError,
    TechniqueCardError,
    validate_bio,
    validate_card,
    validate_display_name,
    validate_handle,
    validate_visibility,
)
from showrun.questions import QuestionError, QuestionsStore
from showrun.store import LessonRecord, ReleaseRecord, ShowrunStore, UserRecord


def _redirect(path: str) -> Response:
    return Response("", status=303, headers=(("Location", path),))


def _page_url(base: str, params: dict[str, str], page: int) -> str:
    """Build a pagination URL preserving non-empty filters (properly encoded)."""

    query = {key: value for key, value in params.items() if value}
    query["page"] = str(page)
    return f"{base}?{urlencode(query)}"


def _json_response(payload: dict[str, Any], *, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
    )


def _base_url(request: Request) -> str:
    configured = os.environ.get("SHOWRUN_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip().rstrip("/")
    if railway_domain:
        if railway_domain.startswith(("http://", "https://")):
            return railway_domain
        return f"https://{railway_domain}"
    scheme = request.headers.get("x-forwarded-proto", "http").split(",", 1)[0]
    host = request.headers.get("host", "127.0.0.1:8000")
    return f"{scheme}://{host}"


def _markdown_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _is_portable_artifact(raw: str, filename: str) -> bool:
    if filename.lower().endswith(".dvd.json"):
        return True
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(candidate, dict) and candidate.get("format") == "dvd/1"


def _import_artifact(raw: str, *, filename: str, title: str = "") -> ShowrunArtifact:
    is_portable = _is_portable_artifact(raw, filename)
    artifact = (
        artifact_from_json(raw)
        if is_portable
        else create_artifact_from_text(raw, filename=filename, title=title)
    )
    if title and is_portable:
        artifact = replace(artifact, title=" ".join(title.split())[:120])
    return artifact


def _initial_time(request: Request, artifact: ShowrunArtifact) -> float:
    raw_chapter = str(request.query.get("chapter") or "")
    if raw_chapter:
        try:
            chapter = int(raw_chapter)
        except ValueError:
            chapter = 0
        if 1 <= chapter <= len(artifact.chapters):
            return artifact.chapters[chapter - 1].at
    raw_start = str(request.query.get("start") or "")
    if raw_start:
        try:
            start = float(raw_start)
        except ValueError:
            start = 0
        if isfinite(start):
            return round(max(0, min(artifact.duration, start)), 1)
    return 0


def _player_context(
    artifact: ShowrunArtifact,
    *,
    state: str,
    manage: bool = False,
    lesson_id: str = "",
    embed: bool = False,
    canonical_url: str = "",
    manifest_url: str = "",
    embed_code: str = "",
    markdown_code: str = "",
    mdx_code: str = "",
    component_code: str = "",
    theme: str = "auto",
    release_slug: str = "",
    initial_time: float = 0,
) -> dict[str, Any]:
    player_config = artifact.player_config()
    player_config["initialTime"] = initial_time
    player_config["embedded"] = embed
    if release_slug:
        player_config["telemetry"] = {
            "endpoint": "/api/v1/events",
            "releaseSlug": release_slug,
        }
    return {
        "canonical_url": canonical_url,
        "chapters": artifact.chapters,
        "description": artifact.description,
        "duration": artifact.duration,
        "embed": embed,
        "embed_code": embed_code,
        "events": artifact.events,
        "lesson_id": lesson_id,
        "manage": manage,
        "manifest_url": manifest_url,
        "markdown_code": markdown_code,
        "mdx_code": mdx_code,
        "component_code": component_code,
        "player_config": player_config,
        "source_format": artifact.source_format,
        "state": state,
        "title": artifact.title,
        "theme": theme,
    }


class ShowrunRoutes:
    """Bind focused request handlers to a configured Chirp application."""

    def __init__(
        self,
        application: App,
        store: ShowrunStore,
        community: CommunityStore,
        questions: QuestionsStore,
    ) -> None:
        self.app = application
        self.store = store
        self.community = community
        self.questions = questions
        self.login_throttle = LoginThrottle()

    def register(self) -> None:
        self.app.route("/", name="library")(self.library)
        self.app.route("/login", name="login")(self.login_page)
        self.app.route("/login", methods=["POST"], name="login.submit")(self.login)
        self.app.route("/signup", name="signup")(self.signup_page)
        self.app.route("/signup", methods=["POST"], name="signup.submit")(self.signup)
        self.app.route("/logout", methods=["POST"], name="logout")(self.logout)
        self.app.route("/settings/tokens", name="tokens.index")(self.tokens_page)
        self.app.route(
            "/settings/tokens",
            methods=["POST"],
            name="tokens.create",
        )(self.create_token)
        self.app.route(
            "/settings/tokens/{token_id}/revoke",
            methods=["POST"],
            name="tokens.revoke",
        )(self.revoke_token)
        self.app.route("/imports/new", name="imports.new")(self.import_page)
        self.app.route("/imports", methods=["POST"], name="imports.create")(self.import_session)
        self.app.route(
            "/api/v1/imports",
            methods=["POST"],
            name="api.imports.create",
        )(self.api_import_session)
        self.app.route("/api/v1/lessons", name="api.lessons.index")(self.api_lessons)
        self.app.route(
            "/api/v1/events",
            methods=["POST"],
            name="api.events.create",
        )(self.playback_event)
        self.app.route("/lessons/{lesson_id}", name="lessons.show")(self.lesson_page)
        self.app.route(
            "/lessons/{lesson_id}/analytics",
            name="lessons.analytics",
        )(self.lesson_analytics_page)
        self.app.route("/lessons/{lesson_id}/edit", name="lessons.edit")(self.edit_lesson_page)
        self.app.route(
            "/lessons/{lesson_id}/edit",
            methods=["POST"],
            name="lessons.update",
        )(self.update_lesson)
        self.app.route(
            "/lessons/{lesson_id}/publish",
            methods=["POST"],
            name="lessons.publish",
        )(self.publish_lesson)
        self.app.route(
            "/lessons/{lesson_id}/duplicate",
            methods=["POST"],
            name="lessons.duplicate",
        )(self.duplicate_lesson)
        self.app.route(
            "/lessons/{lesson_id}/delete",
            methods=["POST"],
            name="lessons.delete",
        )(self.delete_lesson)
        self.app.route(
            "/releases/{slug}/unpublish",
            methods=["POST"],
            name="releases.unpublish",
        )(self.unpublish_release)
        self.app.route("/settings/profile", name="community.profile.settings")(
            self.profile_settings_page
        )
        self.app.route(
            "/settings/profile",
            methods=["POST"],
            name="community.profile.update",
        )(self.update_profile_settings)
        self.app.route("/questions", name="community.questions")(self.questions_index)
        self.app.route("/questions/ask", name="community.questions.ask")(self.question_ask_page)
        self.app.route(
            "/questions",
            methods=["POST"],
            name="community.questions.create",
        )(self.create_question)
        self.app.route("/questions/{slug}", name="community.question")(self.question_page)
        self.app.route(
            "/questions/{slug}/answers",
            methods=["POST"],
            name="community.question.answer",
        )(self.answer_question)
        self.app.route(
            "/questions/{slug}/accept/{answer_id}",
            methods=["POST"],
            name="community.question.accept",
        )(self.accept_answer)
        self.app.route("/discover", name="community.discover")(self.discover)
        self.app.route("/topics", name="community.topics")(self.topics_index)
        self.app.route("/topics/{key}", name="community.topic")(self.topic_page)
        self.app.route("/creators/{handle}", name="community.profile")(self.profile_page)
        self.app.route("/techniques/{slug}", name="community.technique")(self.technique_page)
        self.app.route(
            "/lessons/{lesson_id}/technique",
            name="community.technique.form",
        )(self.technique_form_page)
        self.app.route(
            "/techniques",
            methods=["POST"],
            name="community.technique.publish",
        )(self.publish_technique)
        self.app.route(
            "/techniques/{slug}/fork",
            methods=["POST"],
            name="community.technique.fork",
        )(self.fork_technique)
        self.app.route("/watch/{slug}", name="releases.watch")(self.watch)
        self.app.route("/embed/{slug}", name="releases.embed")(self.embed)
        self.app.route("/releases/{slug}/dvd.json", name="releases.manifest")(self.release_manifest)
        self.app.route("/oembed", name="oembed")(self.oembed)

    def user(self) -> UserRecord | None:
        user = current_user()
        return user if isinstance(user, UserRecord) else None

    def browser_user(self) -> UserRecord | None:
        user = self.user()
        return user if user is not None and not user.scopes else None

    def require_user(self) -> tuple[UserRecord | None, Response | None]:
        user = self.browser_user()
        return (user, None) if user is not None else (None, _redirect("/login"))

    def require_api_scope(self, scope: str) -> tuple[UserRecord | None, Response | None]:
        user = self.user()
        if user is None:
            return None, _json_response({"error": "A valid bearer token is required."}, status=401)
        if scope not in user.scopes:
            return None, _json_response({"error": f"Token needs the {scope} scope."}, status=403)
        return user, None

    async def library(self, request: Request) -> Page:
        user = self.browser_user()
        query = str(request.query.get("q") or "")[:100]
        status = str(request.query.get("status") or "all")
        if status not in {"all", "draft", "published"}:
            status = "all"
        lessons = await self.store.list_lessons(
            workspace_id=user.workspace_id if user else None,
            public_only=user is None,
            query=query,
            status=status,
        )
        metrics = await self.store.usage_metrics(user.workspace_id) if user else None
        return Page(
            "library.html",
            "page_root",
            user=user,
            lessons=lessons,
            metrics=metrics,
            query=query,
            status_filter=status,
        )

    async def login_page(self) -> Page:
        return Page(
            "login.html",
            "page_root",
            error="",
            email="",
        )

    async def login(self, request: Request) -> MutationResult | Page:
        form = await request.form()
        raw_email = str(form.get("email") or "")
        password = str(form.get("password") or "")
        throttle_key = f"login:{request.trusted_client_ip}:{raw_email.strip().lower()}"
        if not self.login_throttle.allow(throttle_key):
            return Page(
                "login.html",
                "page_root",
                error="Too many sign-in attempts. Wait a few minutes and try again.",
                email=raw_email,
            )
        try:
            email = normalize_email(raw_email)
        except ValueError:
            email = raw_email.strip().lower()
        user = await self.store.get_user_by_email(email)
        password_ok = verify_password(password, user.password_hash if user else None)
        if user is None or not password_ok:
            return Page(
                "login.html",
                "page_root",
                error="Email or password is not correct.",
                email=raw_email,
            )
        login(user)
        return MutationResult("/")

    async def logout(self) -> MutationResult:
        logout()
        return MutationResult("/")

    async def signup_page(self) -> Page:
        return Page("signup.html", "page_root", error="", email="", name="")

    async def signup(self, request: Request) -> MutationResult | Page:
        form = await request.form()
        raw_email = str(form.get("email") or "")
        raw_name = str(form.get("name") or "")
        raw_password = str(form.get("password") or "")
        if not self.login_throttle.allow(f"signup:{request.trusted_client_ip}"):
            return Page(
                "signup.html",
                "page_root",
                error="Too many account attempts. Wait a few minutes and try again.",
                email=raw_email,
                name=raw_name,
            )
        try:
            email = normalize_email(raw_email)
            name = validate_name(raw_name)
            hashed = password_hash(raw_password)
        except ValueError as exc:
            return Page(
                "signup.html",
                "page_root",
                error=str(exc),
                email=raw_email,
                name=raw_name,
            )
        if await self.store.get_user_by_email(email) is not None:
            return Page(
                "signup.html",
                "page_root",
                error="An account with that email already exists.",
                email=raw_email,
                name=raw_name,
            )
        try:
            user = await self.store.create_user(email=email, name=name, password_hash=hashed)
        except QueryError:
            if await self.store.get_user_by_email(email) is None:
                raise
            return Page(
                "signup.html",
                "page_root",
                error="An account with that email already exists.",
                email=raw_email,
                name=raw_name,
            )
        login(user)
        return MutationResult("/")

    async def tokens_page(self) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        tokens = await self.store.list_api_tokens(user)
        return Page(
            "tokens.html",
            "page_root",
            user=user,
            tokens=tokens,
            plaintext_token="",
            error="",
        )

    async def create_token(self, request: Request) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        form = await request.form()
        name = " ".join(str(form.get("name") or "").split())
        if not name or len(name) > 80:
            return Page(
                "tokens.html",
                "page_root",
                user=user,
                tokens=await self.store.list_api_tokens(user),
                plaintext_token="",
                error="Give the token a name of 80 characters or fewer.",
            )
        plaintext, prefix, digest = issue_token()
        await self.store.create_api_token(
            user=user,
            name=name,
            token_prefix=prefix,
            token_hash=digest,
        )
        await self.store.record_usage("token.created", workspace_id=user.workspace_id)
        return Page(
            "tokens.html",
            "page_root",
            user=user,
            tokens=await self.store.list_api_tokens(user),
            plaintext_token=plaintext,
            error="",
        )

    async def revoke_token(self, token_id: str) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        await self.store.revoke_api_token(user, token_id)
        return MutationResult("/settings/tokens")

    async def import_page(self) -> Page | Response:
        _user, denied = self.require_user()
        if denied:
            return denied
        return Page("import.html", "page_root", error="")

    async def _persist_import(
        self,
        *,
        user: UserRecord,
        artifact: ShowrunArtifact,
        digest: str,
        channel: str,
    ) -> tuple[LessonRecord, bool]:
        duplicate = await self.store.find_duplicate(user.workspace_id, digest)
        if duplicate is not None:
            return duplicate, True
        try:
            lesson = await self.store.create_draft(
                artifact,
                workspace_id=user.workspace_id,
                source_sha256=digest,
            )
        except QueryError:
            duplicate = await self.store.find_duplicate(user.workspace_id, digest)
            if duplicate is None:
                raise
            return duplicate, True
        await self.store.record_usage(
            "lesson.imported",
            workspace_id=user.workspace_id,
            lesson_id=lesson.id,
            properties={"source_format": artifact.source_format, "channel": channel},
        )
        return lesson, False

    async def import_session(self, request: Request) -> MutationResult | Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        form = await request.form()
        title = str(form.get("title") or "").strip()
        pasted = str(form.get("transcript") or "").strip()
        upload = form.get("session_file")
        filename = "pasted-session.jsonl"
        transcript = pasted
        if isinstance(upload, UploadFile) and upload.size:
            filename = upload.filename
            try:
                transcript = (await upload.read()).decode("utf-8")
            except UnicodeDecodeError:
                return Page(
                    "import.html",
                    "page_root",
                    error="Session files must be UTF-8 JSONL.",
                )
        if not transcript:
            return Page(
                "import.html",
                "page_root",
                error="Choose a JSONL file or paste a session.",
            )
        try:
            artifact = _import_artifact(transcript, filename=filename, title=title)
        except ValueError as exc:
            return Page("import.html", "page_root", error=str(exc))
        digest_source = (
            artifact.to_json() if _is_portable_artifact(transcript, filename) else transcript
        )
        digest = hashlib.sha256(digest_source.encode()).hexdigest()
        lesson, _duplicate = await self._persist_import(
            user=user,
            artifact=artifact,
            digest=digest,
            channel="browser",
        )
        return MutationResult(f"/lessons/{lesson.id}/edit")

    async def api_import_session(self, request: Request) -> Response:
        user, denied = self.require_api_scope("imports:write")
        if denied or user is None:
            return denied or _json_response({"error": "Unauthorized"}, status=401)
        try:
            payload = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError, ValueError:
            return _json_response({"error": "Send a JSON request body."}, status=400)
        if not isinstance(payload, dict):
            return _json_response({"error": "The request body must be a JSON object."}, status=400)
        transcript = str(payload.get("transcript") or "")
        filename = str(payload.get("filename") or "session.jsonl")[:255]
        title = str(payload.get("title") or "")
        portable = payload.get("artifact")
        if isinstance(portable, dict):
            transcript = json.dumps(portable, ensure_ascii=False, separators=(",", ":"))
            filename = filename if filename.endswith(".dvd.json") else "lesson.dvd.json"
        if not transcript:
            return _json_response({"error": "transcript or artifact is required."}, status=422)
        try:
            artifact = _import_artifact(transcript, filename=filename, title=title)
        except ValueError as exc:
            return _json_response({"error": str(exc)}, status=422)
        digest_source = (
            artifact.to_json() if _is_portable_artifact(transcript, filename) else transcript
        )
        digest = hashlib.sha256(digest_source.encode()).hexdigest()
        lesson, duplicate = await self._persist_import(
            user=user,
            artifact=artifact,
            digest=digest,
            channel="api",
        )
        return _json_response(
            {
                "duplicate": duplicate,
                "lesson_id": lesson.id,
                "lesson_url": f"/lessons/{lesson.id}/edit",
                "warnings": list(lesson.artifact.warnings),
            },
            status=200 if duplicate else 201,
        )

    async def api_lessons(self) -> Response:
        user, denied = self.require_api_scope("imports:write")
        if denied or user is None:
            return denied or _json_response({"error": "Unauthorized"}, status=401)
        lessons = await self.store.list_lessons(workspace_id=user.workspace_id)
        return _json_response({"lessons": [asdict(lesson) for lesson in lessons]})

    async def playback_event(self, request: Request) -> Response:
        try:
            payload = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError, ValueError:
            return _json_response({"error": "Send a JSON request body."}, status=400)
        if not isinstance(payload, dict):
            return _json_response({"error": "The request body must be a JSON object."}, status=400)
        slug = str(payload.get("releaseSlug") or "")[:100]
        event_name = str(payload.get("event") or "")
        allowed = {
            "playback.started",
            "playback.completed",
            "chapter.viewed",
        }
        if event_name not in allowed:
            return _json_response({"error": "Unknown playback event."}, status=422)
        release = await self.store.get_release(slug)
        if release is None:
            return _json_response({"error": "Showrun not found."}, status=404)
        properties: dict[str, str | int | float | bool] = {}
        origin = str(payload.get("origin") or "")[:255]
        if origin.startswith(("http://", "https://")):
            properties["origin"] = origin
        if event_name == "chapter.viewed":
            try:
                chapter = int(payload.get("chapter") or 0)
            except TypeError, ValueError:
                chapter = 0
            if not 1 <= chapter <= len(release.artifact.chapters):
                return _json_response({"error": "Invalid chapter."}, status=422)
            properties["chapter"] = chapter
        await self.store.record_usage(
            event_name,
            lesson_id=release.lesson_id,
            release_id=release.id,
            properties=properties,
        )
        return Response("", status=204)

    async def edit_lesson_page(
        self,
        lesson_id: str,
        request: Request,
    ) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
        if lesson is None:
            return Response("Lesson not found", status=404, content_type="text/plain")
        releases = await self.store.list_releases(lesson.id, workspace_id=user.workspace_id)
        return await self._editor_page(
            lesson,
            error="",
            saved=str(request.query.get("saved") or "") == "1",
            releases=releases,
        )

    async def lesson_analytics_page(self, lesson_id: str) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
        if lesson is None:
            return Response("Lesson not found", status=404, content_type="text/plain")
        analytics = await self.store.lesson_analytics(
            lesson_id,
            workspace_id=user.workspace_id,
        )
        return Page(
            "analytics.html",
            "page_root",
            analytics=analytics,
            lesson=lesson,
        )

    async def _editor_page(
        self,
        lesson: LessonRecord,
        *,
        error: str,
        releases: list[ReleaseRecord],
        saved: bool = False,
    ) -> Page:
        # Show source attribution before publication when this lesson is a fork.
        ancestry = await self.community.fork_ancestry(lesson.id)
        return Page(
            "editor.html",
            "page_root",
            artifact=lesson.artifact,
            error=error,
            lesson=lesson,
            releases=releases,
            saved=saved,
            fork_source=ancestry[0] if ancestry else None,
        )

    async def update_lesson(self, request: Request, lesson_id: str) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
        if lesson is None:
            return Response("Lesson not found", status=404, content_type="text/plain")
        form = await request.form()
        artifact = lesson.artifact
        included_ids = {
            event.id
            for event in artifact.events
            if str(form.get(f"event_{event.id}_include") or "")
        }
        durations = {
            event.id: str(form.get(f"event_{event.id}_duration") or "") for event in artifact.events
        }
        orders = {
            event.id: str(form.get(f"event_{event.id}_order") or event.id)
            for event in artifact.events
        }
        pauses = {
            event.id: str(form.get(f"event_{event.id}_pause") or event.pause_after)
            for event in artifact.events
        }
        labels = {
            event.id: str(form.get(f"event_{event.id}_label") or event.label)
            for event in artifact.events
        }
        texts = {
            event.id: str(form.get(f"event_{event.id}_text") or event.text)
            for event in artifact.events
        }
        chapters = tuple(
            {
                "include": str(form.get(f"chapter_{index}_include") or ""),
                "order": str(form.get(f"chapter_{index}_order") or ""),
                "name": str(form.get(f"chapter_{index}_name") or ""),
                "at": str(form.get(f"chapter_{index}_at") or ""),
                "caption": str(form.get(f"chapter_{index}_caption") or ""),
                "note": str(form.get(f"chapter_{index}_note") or ""),
                "teaching_point": str(form.get(f"chapter_{index}_teaching_point") or ""),
            }
            for index in range(len(artifact.chapters) + 1)
        )
        try:
            directed = direct_artifact(
                artifact,
                title=str(form.get("title") or ""),
                description=str(form.get("description") or ""),
                included_event_ids=included_ids,
                event_durations=durations,
                chapter_values=chapters,
                event_orders=orders,
                event_pauses=pauses,
                event_labels=labels,
                event_texts=texts,
            )
        except ValueError as exc:
            releases = await self.store.list_releases(lesson.id, workspace_id=user.workspace_id)
            return await self._editor_page(lesson, error=str(exc), releases=releases)
        await self.store.update_lesson(
            lesson_id,
            workspace_id=user.workspace_id,
            artifact=directed,
        )
        return _redirect(f"/lessons/{lesson_id}/edit?saved=1")

    async def duplicate_lesson(self, lesson_id: str) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
        if lesson is None:
            return Response("Lesson not found", status=404, content_type="text/plain")
        artifact = replace(
            lesson.artifact,
            title=f"Copy of {lesson.title}"[:120],
        )
        duplicate = await self.store.create_draft(
            artifact,
            workspace_id=user.workspace_id,
            source_sha256=hashlib.sha256(
                f"{lesson.id}:{os.urandom(16).hex()}".encode()
            ).hexdigest(),
        )
        return MutationResult(f"/lessons/{duplicate.id}/edit")

    async def delete_lesson(self, lesson_id: str) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        try:
            await self.store.delete_draft(lesson_id, workspace_id=user.workspace_id)
        except LookupError:
            return Response("Lesson not found", status=404, content_type="text/plain")
        except ValueError as exc:
            return Response(str(exc), status=409, content_type="text/plain")
        return MutationResult("/")

    async def unpublish_release(self, slug: str) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        try:
            lesson_id = await self.store.unpublish_release(
                slug,
                workspace_id=user.workspace_id,
            )
        except LookupError:
            return Response("Release not found", status=404, content_type="text/plain")
        return MutationResult(f"/lessons/{lesson_id}/edit")

    async def lesson_page(self, lesson_id: str) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
        if lesson is None:
            return Response("Lesson not found", status=404, content_type="text/plain")
        return Page(
            "player.html",
            "page_root",
            **_player_context(
                lesson.artifact,
                state=f"draft r{lesson.revision}",
                manage=True,
                lesson_id=lesson.id,
            ),
        )

    async def publish_lesson(
        self,
        request: Request,
        lesson_id: str,
    ) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        form = await request.form()
        visibility = str(form.get("visibility") or "unlisted")
        try:
            lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
            if lesson is None:
                raise LookupError("Lesson not found")
            existing = await self.store.get_release_for_revision(
                lesson.id,
                lesson.revision,
                visibility,
            )
            release = await self.store.publish(
                lesson_id,
                visibility,
                workspace_id=user.workspace_id,
            )
        except ValueError as exc:
            return Response(str(exc), status=422, content_type="text/plain")
        except LookupError:
            return Response("Lesson not found", status=404, content_type="text/plain")
        if existing is None:
            await self.store.record_usage(
                "lesson.published",
                workspace_id=user.workspace_id,
                lesson_id=lesson_id,
                release_id=release.id,
                properties={"visibility": release.visibility, "revision": release.revision},
            )
        return MutationResult(f"/watch/{release.slug}")

    # -- Community Hub ------------------------------------------------------

    async def _ensure_profile(self, user: UserRecord):
        return await self.community.ensure_profile(
            user_id=user.id,
            workspace_id=user.workspace_id,
            display_name=user.name,
            email=user.email,
        )

    async def profile_settings_page(self, request: Request) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        profile = await self._ensure_profile(user)
        return Page(
            "profile_settings.html",
            "page_root",
            user=user,
            profile=profile,
            error="",
            saved=str(request.query.get("saved") or "") == "1",
        )

    async def update_profile_settings(self, request: Request) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        profile = await self._ensure_profile(user)
        form = await request.form()
        raw_name = str(form.get("display_name") or "")
        raw_bio = str(form.get("bio") or "")
        raw_visibility = str(form.get("visibility") or "public")
        raw_handle = str(form.get("handle") or "")

        def _reject(message: str) -> Page:
            return Page(
                "profile_settings.html",
                "page_root",
                user=user,
                profile=replace(
                    profile,
                    handle=raw_handle.strip().lower() or profile.handle,
                    display_name=raw_name.strip() or profile.display_name,
                    bio=raw_bio.strip(),
                    visibility=raw_visibility
                    if raw_visibility in {"public", "private"}
                    else profile.visibility,
                ),
                error=message,
                saved=False,
            )

        try:
            display_name = validate_display_name(raw_name)
            bio = validate_bio(raw_bio)
            visibility = validate_visibility(raw_visibility)
            handle = validate_handle(raw_handle)
        except ProfileError as exc:
            return _reject(str(exc))
        try:
            if handle != profile.handle:
                await self.community.change_handle(user_id=user.id, new_handle=handle)
        except ProfileError as exc:
            return _reject(str(exc))
        await self.community.update_profile(
            user_id=user.id,
            display_name=display_name,
            bio=bio,
            visibility=visibility,
        )
        return _redirect("/settings/profile?saved=1")

    def _page_number(self, request: Request) -> int:
        raw = str(request.query.get("page") or "1")
        return int(raw) if raw.isdigit() and int(raw) > 0 else 1

    async def discover(self, request: Request) -> Page:
        user = self.browser_user()
        query = str(request.query.get("q") or "")[:100]
        topic = str(request.query.get("topic") or "")[:64]
        page_num = self._page_number(request)
        result = await self.community.discover_page(query=query, topic=topic, page=page_num)
        topics = await self.community.list_public_topics()
        total = await self.community.public_technique_count()
        params = {"q": query, "topic": topic}
        prev_url = _page_url("/discover", params, result.page - 1) if result.has_prev else ""
        next_url = _page_url("/discover", params, result.page + 1) if result.has_next else ""
        return Page(
            "discover.html",
            "page_root",
            user=user,
            page=result,
            topics=topics,
            total=total,
            query=query,
            active_topic=topic,
            prev_url=prev_url,
            next_url=next_url,
        )

    async def topics_index(self, request: Request) -> Page:
        user = self.browser_user()
        catalog = await self.community.list_topic_catalog()
        return Page(
            "topics_index.html",
            "page_root",
            user=user,
            catalog=catalog,
        )

    async def topic_page(self, key: str, request: Request) -> Page:
        user = self.browser_user()
        page_num = self._page_number(request)
        result = await self.community.discover_page(topic=key, page=page_num)
        count = await self.community.public_technique_count(topic=key)
        base = f"/topics/{key}"
        prev_url = _page_url(base, {}, result.page - 1) if result.has_prev else ""
        next_url = _page_url(base, {}, result.page + 1) if result.has_next else ""
        return Page(
            "topic.html",
            "page_root",
            user=user,
            topic_key=key,
            page=result,
            count=count,
            prev_url=prev_url,
            next_url=next_url,
        )

    # -- Questions & demonstrated answers -----------------------------------

    async def questions_index(self, request: Request) -> Page:
        user = self.browser_user()
        questions = await self.questions.list_questions()
        return Page("questions.html", "page_root", user=user, questions=questions)

    async def question_ask_page(self, request: Request) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        topics = await self.community.list_topics()
        return Page(
            "question_ask.html",
            "page_root",
            user=user,
            topic_catalog=topics,
            error="",
            title="",
            body="",
            topics_value="",
        )

    async def create_question(self, request: Request) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        profile = await self._ensure_profile(user)
        form = await request.form()
        title = str(form.get("title") or "")
        body = str(form.get("body") or "")
        topics = str(form.get("topics") or "")
        try:
            question = await self.questions.ask_question(
                asker_profile_id=profile.id,
                workspace_id=user.workspace_id,
                title=title,
                body=body,
                topics=topics,
            )
        except QuestionError as exc:
            catalog = await self.community.list_topics()
            return Page(
                "question_ask.html",
                "page_root",
                user=user,
                topic_catalog=catalog,
                error=str(exc),
                title=title,
                body=body,
                topics_value=topics,
            )
        await self.store.record_usage(
            "question.asked",
            workspace_id=user.workspace_id,
            properties={"question": question.slug},
        )
        return _redirect(f"/questions/{question.slug}")

    async def question_page(self, slug: str, request: Request) -> Page | Response:
        user = self.browser_user()
        question = await self.questions.get_question(slug)
        if question is None:
            return Response("Question not found", status=404, content_type="text/plain")
        answers = await self.questions.list_answers(question.id)
        is_asker = bool(user and user.workspace_id == question.workspace_id)
        my_techniques: list[Any] = []
        if user is not None:
            profile = await self._ensure_profile(user)
            # A user answers with their own publicly-eligible techniques.
            my_techniques = await self.community.list_techniques_by_handle(
                profile.handle, viewer_workspace_id=None
            )
        return Page(
            "question_detail.html",
            "page_root",
            user=user,
            question=question,
            answers=answers,
            is_asker=is_asker,
            my_techniques=my_techniques,
        )

    async def answer_question(self, slug: str, request: Request) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        profile = await self._ensure_profile(user)
        form = await request.form()
        technique_slug = str(form.get("technique_slug") or "").strip()
        try:
            _question, _answer_id = await self.questions.answer_question(
                answerer_profile_id=profile.id,
                workspace_id=user.workspace_id,
                question_slug=slug,
                technique_slug=technique_slug,
            )
        except QuestionError as exc:
            return Response(str(exc), status=422, content_type="text/plain")
        except LookupError:
            return Response("Question not found", status=404, content_type="text/plain")
        await self.store.record_usage(
            "question.answered",
            workspace_id=user.workspace_id,
            properties={"question": slug},
        )
        return MutationResult(f"/questions/{slug}")

    async def accept_answer(
        self,
        slug: str,
        answer_id: str,
        request: Request,
    ) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        try:
            await self.questions.accept_answer(
                asker_workspace_id=user.workspace_id,
                question_slug=slug,
                answer_id=answer_id,
            )
        except PermissionError:
            return Response("Only the asker can accept.", status=403, content_type="text/plain")
        except LookupError:
            return Response("Not found", status=404, content_type="text/plain")
        await self.store.record_usage(
            "answer.accepted",
            workspace_id=user.workspace_id,
            properties={"question": slug},
        )
        return MutationResult(f"/questions/{slug}")

    async def profile_page(self, handle: str, request: Request) -> Page | Response:
        user = self.browser_user()
        viewer_workspace = user.workspace_id if user else None
        current = await self.community.resolve_handle(handle)
        if current is None:
            return Response("Creator not found", status=404, content_type="text/plain")
        profile = await self.community.get_public_profile(
            current,
            viewer_workspace_id=viewer_workspace,
        )
        # Gate visibility before redirecting so a private profile 404s whether
        # reached by its current handle or a past alias (no existence leak).
        if profile is None:
            return Response("Creator not found", status=404, content_type="text/plain")
        if current != handle:
            return Response(
                "", status=301, headers=(("Location", f"/creators/{current}"),)
            )
        techniques = await self.community.list_techniques_by_handle(
            current,
            viewer_workspace_id=viewer_workspace,
        )
        signals = await self.community.craft_signals(current)
        return Page(
            "profile.html",
            "page_root",
            user=user,
            profile=profile,
            techniques=techniques,
            signals=signals,
            is_owner=bool(user and user.workspace_id == profile.workspace_id),
        )

    async def technique_page(self, slug: str, request: Request) -> Page | Response:
        user = self.browser_user()
        viewer_workspace = user.workspace_id if user else None
        card = await self.community.get_technique_card(
            slug,
            viewer_workspace_id=viewer_workspace,
        )
        if card is None:
            return Response("Technique not found", status=404, content_type="text/plain")
        topics = await self.community.list_topics_for_technique(card.id)
        versions = await self.community.list_version_views(
            slug,
            viewer_workspace_id=viewer_workspace,
        )
        is_owner = bool(user and user.workspace_id == card.workspace_id)
        # Reuse the deployed player via its embed route (no duplication) and
        # surface bounded, public-safe evidence from the same immutable release.
        release = await self.store.get_release(card.release_slug)
        evidence_events = (
            [event for event in release.artifact.events if event.activity][:8]
            if release is not None
            else []
        )
        chapters = release.artifact.chapters if release is not None else ()
        # Chapter/time deep-links: reflect ?chapter=/?start= into the embedded
        # player so a technique is linkable at a precise moment.
        active_chapter = 0
        embed_query = ""
        raw_chapter = str(request.query.get("chapter") or "")
        raw_start = str(request.query.get("start") or "")
        if raw_chapter.isdigit() and 1 <= int(raw_chapter) <= len(chapters):
            active_chapter = int(raw_chapter)
            embed_query = f"?chapter={active_chapter}"
        elif raw_start:
            try:
                start = float(raw_start)
            except ValueError:
                start = -1
            if isfinite(start) and start >= 0:
                embed_query = f"?start={round(start, 1)}"
        embed_src = f"/embed/{card.release_slug}{embed_query}"
        canonical = f"{_base_url(request)}/techniques/{card.slug}"
        ancestry = await self.community.fork_ancestry(card.lesson_id)
        if not is_owner:
            await self.store.record_usage(
                "technique.viewed",
                lesson_id=None,
                release_id=card.release_id,
                properties={"technique": card.slug},
            )
        return Page(
            "technique.html",
            "page_root",
            user=user,
            card=card,
            topics=topics,
            versions=versions,
            evidence_events=evidence_events,
            chapters=chapters,
            active_chapter=active_chapter,
            embed_src=embed_src,
            canonical_url=canonical,
            ancestry=ancestry,
            can_fork=user is not None,
            can_embed=release is not None,
            is_owner=is_owner,
        )

    async def technique_form_page(
        self,
        lesson_id: str,
        request: Request,
    ) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        lesson = await self.store.get_lesson(lesson_id, workspace_id=user.workspace_id)
        if lesson is None:
            return Response("Lesson not found", status=404, content_type="text/plain")
        releases = await self.store.list_releases(lesson.id, workspace_id=user.workspace_id)
        public_release = next(
            (r for r in releases if r.visibility == "public" and r.disabled_at is None),
            None,
        )
        existing = await self.community.owned_card_by_lesson(
            lesson.id,
            workspace_id=user.workspace_id,
        )
        topics_value = ""
        if existing is not None:
            topics_value = await self.community.topics_csv(existing.id)
        topics = await self.community.list_topics()
        return self._technique_form(
            lesson=lesson,
            public_release=public_release,
            card=existing,
            topics_value=topics_value,
            topic_catalog=topics,
            error="",
        )

    def _technique_form(
        self,
        *,
        lesson: LessonRecord,
        public_release: ReleaseRecord | None,
        card: Any,
        topics_value: str,
        topic_catalog: Any,
        error: str,
    ) -> Page:
        return Page(
            "technique_form.html",
            "page_root",
            lesson=lesson,
            public_release=public_release,
            release_slug=public_release.slug if public_release else "",
            card=card,
            topics_value=topics_value,
            topic_catalog=topic_catalog,
            error=error,
        )

    async def publish_technique(self, request: Request) -> Page | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        form = await request.form()
        release_slug = str(form.get("release_slug") or "").strip()
        release = await self.store.get_release(release_slug)
        lesson = (
            await self.store.get_lesson(release.lesson_id, workspace_id=user.workspace_id)
            if release is not None
            else None
        )
        if release is None or lesson is None:
            return Response("Release not found", status=404, content_type="text/plain")
        topic_catalog = await self.community.list_topics()

        def _reject(message: str) -> Page:
            return self._technique_form(
                lesson=lesson,
                public_release=release,
                card=None,
                topics_value=str(form.get("topics") or ""),
                topic_catalog=topic_catalog,
                error=message,
            )

        try:
            card = validate_card(
                problem=str(form.get("problem") or ""),
                pattern=str(form.get("pattern") or ""),
                use_when=str(form.get("use_when") or ""),
                objective=str(form.get("objective") or ""),
                summary=str(form.get("summary") or ""),
                limitations=str(form.get("limitations") or ""),
                topics=str(form.get("topics") or ""),
            )
        except TechniqueCardError as exc:
            return _reject(str(exc))
        try:
            technique, _version, created = await self.community.publish_technique_version(
                user_id=user.id,
                workspace_id=user.workspace_id,
                display_name=user.name,
                email=user.email,
                release_slug=release_slug,
                card=card,
            )
        except TechniqueCardError as exc:
            return _reject(str(exc))
        except LookupError:
            return Response("Release not found", status=404, content_type="text/plain")
        if created:
            await self.store.record_usage(
                "technique.published",
                workspace_id=user.workspace_id,
                lesson_id=lesson.id,
                release_id=release.id,
                properties={"technique": technique.slug},
            )
        return _redirect(f"/techniques/{technique.slug}")

    async def fork_technique(self, slug: str, request: Request) -> MutationResult | Response:
        user, denied = self.require_user()
        if denied or user is None:
            return denied or _redirect("/login")
        # Only a publicly eligible technique can be forked.
        card = await self.community.get_technique_card(slug)
        if card is None:
            return Response("Technique not found", status=404, content_type="text/plain")
        # Idempotent per source technique: re-forking returns the same draft.
        request_key = f"technique:{card.id}"
        existing = await self.community.existing_fork(user.workspace_id, request_key)
        if existing is not None:
            return MutationResult(f"/lessons/{existing}/edit")
        release = await self.store.get_release(card.release_slug)
        if release is None:
            return Response("Source release unavailable", status=409, content_type="text/plain")
        # The source artifact re-crosses the sanitization/validation boundary.
        child = await self.store.create_draft(
            replace(release.artifact, title=f"Fork of {card.title}"[:120]),
            workspace_id=user.workspace_id,
            source_sha256=hashlib.sha256(
                f"fork:{card.version_id}:{os.urandom(16).hex()}".encode()
            ).hexdigest(),
        )
        source_profile = await self.community.get_public_profile(card.handle)
        if source_profile is not None:
            inserted = await self.community.record_fork(
                child_lesson_id=child.id,
                child_workspace_id=user.workspace_id,
                source_technique_id=card.id,
                source_version_id=card.version_id,
                source_profile_id=source_profile.id,
                request_key=request_key,
            )
            if not inserted:
                # Lost a race; reuse the winning fork's draft.
                winner = await self.community.existing_fork(user.workspace_id, request_key)
                if winner is not None and winner != child.id:
                    return MutationResult(f"/lessons/{winner}/edit")
        await self.store.record_usage(
            "technique.forked",
            workspace_id=user.workspace_id,
            lesson_id=child.id,
            properties={"source": card.slug},
        )
        return MutationResult(f"/lessons/{child.id}/edit")

    async def _release(self, slug: str) -> ReleaseRecord | Response:
        release = await self.store.get_release(slug)
        if release is None:
            return Response("Showrun not found", status=404, content_type="text/plain")
        return release

    async def watch(self, request: Request, slug: str) -> Page | Response:
        release = await self._release(slug)
        if isinstance(release, Response):
            return release
        base_url = _base_url(request)
        canonical = f"{base_url}/watch/{release.slug}"
        embed_url = f"{base_url}/embed/{release.slug}"
        safe_title = html.escape(release.artifact.title, quote=True)
        embed_code = (
            f'<iframe src="{embed_url}" '
            f'title="{safe_title}" '
            'loading="lazy" style="width:100%;aspect-ratio:16/9;border:0" '
            "allowfullscreen></iframe>"
        )
        mdx_code = (
            f'<iframe src="{embed_url}" title="{safe_title}" loading="lazy" '
            'style={{width:"100%",aspectRatio:"16/9",border:0}} allowFullScreen />'
        )
        component_code = (
            f'<script defer src="{base_url}/static/embed.js"></script>\n'
            f'<showrun-player src="{embed_url}" title="{safe_title}"></showrun-player>'
        )
        markdown_code = f"[Watch {_markdown_label(release.artifact.title)} on Showrun]({canonical})"
        user = self.browser_user()
        lesson = await self.store.get_lesson(release.lesson_id)
        author_preview = bool(
            user is not None and lesson is not None and lesson.workspace_id == user.workspace_id
        )
        await self.store.record_usage(
            "release.author_previewed" if author_preview else "release.viewed",
            lesson_id=release.lesson_id,
            release_id=release.id,
        )
        return Page(
            "player.html",
            "page_root",
            **_player_context(
                release.artifact,
                state=f"release r{release.revision}",
                canonical_url=canonical,
                manifest_url=f"/releases/{release.slug}/dvd.json",
                embed_code=embed_code,
                markdown_code=markdown_code,
                mdx_code=mdx_code,
                component_code=component_code,
                release_slug=release.slug,
                initial_time=_initial_time(request, release.artifact),
            ),
        )

    async def embed(self, request: Request, slug: str) -> Page | Response:
        release = await self._release(slug)
        if isinstance(release, Response):
            return release
        base_url = _base_url(request)
        theme = str(request.query.get("theme") or "auto").lower()
        if theme not in {"auto", "light", "dark"}:
            theme = "auto"
        await self.store.record_usage(
            "release.embedded",
            lesson_id=release.lesson_id,
            release_id=release.id,
        )
        return Page(
            "player.html",
            "page_root",
            **_player_context(
                release.artifact,
                state=f"release r{release.revision}",
                embed=True,
                canonical_url=f"{base_url}/watch/{release.slug}",
                theme=theme,
                release_slug=release.slug,
                initial_time=_initial_time(request, release.artifact),
            ),
        )

    async def release_manifest(self, slug: str) -> Response:
        release = await self.store.get_release(slug)
        if release is None:
            return Response("Showrun not found", status=404, content_type="text/plain")
        await self.store.record_usage(
            "release.manifest_downloaded",
            lesson_id=release.lesson_id,
            release_id=release.id,
        )
        return Response(
            release.manifest_json,
            content_type="application/json; charset=utf-8",
            headers=(
                ("Content-Disposition", f'attachment; filename="{release.slug}.dvd.json"'),
                ("Cache-Control", "public, max-age=31536000, immutable"),
            ),
        )

    async def oembed(self, request: Request) -> Response:
        url = str(request.query.get("url") or "")
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        release = await self.store.get_release(slug)
        if release is None:
            return Response(
                json.dumps({"error": "Showrun not found"}),
                status=404,
                content_type="application/json",
            )
        base_url = _base_url(request)
        safe_title = html.escape(release.artifact.title, quote=True)
        iframe = (
            f'<iframe src="{base_url}/embed/{release.slug}" '
            f'title="{safe_title}" loading="lazy" '
            'style="width:100%;aspect-ratio:16/9;border:0" allowfullscreen></iframe>'
        )
        payload = {
            "type": "rich",
            "version": "1.0",
            "provider_name": "Showrun",
            "provider_url": base_url,
            "title": release.artifact.title,
            "html": iframe,
            "width": 1280,
            "height": 720,
        }
        return Response(
            json.dumps(payload),
            content_type="application/json; charset=utf-8",
            headers=(("Cache-Control", "public, max-age=300"),),
        )
