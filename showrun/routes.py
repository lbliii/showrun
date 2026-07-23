"""Command-oriented HTTP routes for the Showrun vertical slice."""

from __future__ import annotations

import hashlib
import html
import json
from typing import Any

from chirp.app import App
from chirp.data import QueryError
from chirp.http.forms import UploadFile
from chirp.http.request import Request
from chirp.http.response import Response
from chirp.middleware.auth import current_user, login, logout
from chirp.templating.returns import MutationResult, Page

from showrun.artifacts import ShowrunArtifact, create_artifact_from_text
from showrun.auth import (
    LoginThrottle,
    issue_token,
    normalize_email,
    password_hash,
    validate_name,
    verify_password,
)
from showrun.store import ReleaseRecord, ShowrunStore, UserRecord


def _redirect(path: str) -> Response:
    return Response("", status=303, headers=(("Location", path),))


def _base_url(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", "http").split(",", 1)[0]
    host = request.headers.get("host", "127.0.0.1:8000")
    return f"{scheme}://{host}"


def _player_context(
    artifact: ShowrunArtifact,
    *,
    state: str,
    manage: bool = False,
    lesson_id: str = "",
    embed: bool = False,
    canonical_url: str = "",
    manifest_url: str = "",
) -> dict[str, Any]:
    return {
        "canonical_url": canonical_url,
        "chapters": artifact.chapters,
        "description": artifact.description,
        "duration": artifact.duration,
        "embed": embed,
        "events": artifact.events,
        "lesson_id": lesson_id,
        "manage": manage,
        "manifest_url": manifest_url,
        "player_config": artifact.player_config(),
        "source_format": artifact.source_format,
        "state": state,
        "title": artifact.title,
    }


class ShowrunRoutes:
    """Bind focused request handlers to a configured Chirp application."""

    def __init__(self, application: App, store: ShowrunStore) -> None:
        self.app = application
        self.store = store
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
        self.app.route("/lessons/{lesson_id}", name="lessons.show")(self.lesson_page)
        self.app.route(
            "/lessons/{lesson_id}/publish",
            methods=["POST"],
            name="lessons.publish",
        )(self.publish_lesson)
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

    async def library(self) -> Page:
        user = self.browser_user()
        lessons = await self.store.list_lessons(
            workspace_id=user.workspace_id if user else None,
            public_only=user is None,
        )
        return Page("library.html", "page_root", user=user, lessons=lessons)

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
        key = request.client[0] if request.client else "unknown"
        if not self.login_throttle.allow(f"login:{key}"):
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
        if user is None or not verify_password(password, user.password_hash if user else None):
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
        key = request.client[0] if request.client else "unknown"
        if not self.login_throttle.allow(f"signup:{key}"):
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
            artifact = create_artifact_from_text(transcript, filename=filename, title=title)
        except ValueError as exc:
            return Page("import.html", "page_root", error=str(exc))
        lesson = await self.store.create_draft(
            artifact,
            workspace_id=user.workspace_id,
            source_sha256=hashlib.sha256(transcript.encode()).hexdigest(),
        )
        return MutationResult(f"/lessons/{lesson.id}")

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
            release = await self.store.publish(
                lesson_id,
                visibility,
                workspace_id=user.workspace_id,
            )
        except ValueError as exc:
            return Response(str(exc), status=422, content_type="text/plain")
        except LookupError:
            return Response("Lesson not found", status=404, content_type="text/plain")
        return MutationResult(f"/watch/{release.slug}")

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
        return Page(
            "player.html",
            "page_root",
            **_player_context(
                release.artifact,
                state=f"release r{release.revision}",
                canonical_url=canonical,
                manifest_url=f"/releases/{release.slug}/dvd.json",
            ),
        )

    async def embed(self, request: Request, slug: str) -> Page | Response:
        release = await self._release(slug)
        if isinstance(release, Response):
            return release
        base_url = _base_url(request)
        return Page(
            "player.html",
            "page_root",
            **_player_context(
                release.artifact,
                state=f"release r{release.revision}",
                embed=True,
                canonical_url=f"{base_url}/watch/{release.slug}",
            ),
        )

    async def release_manifest(self, slug: str) -> Response:
        release = await self.store.get_release(slug)
        if release is None:
            return Response("Showrun not found", status=404, content_type="text/plain")
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
