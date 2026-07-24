"""Application factory for Showrun's persistent web product."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from chirp.app import App
from chirp.config import AppConfig
from chirp.markdown import register_markdown_filter
from chirp.middleware.auth import AuthConfig
from chirp.middleware.csrf import CSRFConfig
from chirp.middleware.security_headers import SecurityHeadersConfig
from chirp.middleware.stack import secure_stack

from showrun.artifacts import load_artifact
from showrun.auth import verify_api_token
from showrun.community import CommunityStore
from showrun.embed_policy import PublicEmbedPolicy
from showrun.golden import sync_golden
from showrun.questions import QuestionsStore
from showrun.routes import ShowrunRoutes
from showrun.store import ShowrunStore

PACKAGE_ROOT = Path(__file__).parent
SOURCE_ROOT = PACKAGE_ROOT.parent
BUNDLED_WEB = PACKAGE_ROOT / "_web"
ROOT = BUNDLED_WEB if BUNDLED_WEB.is_dir() else SOURCE_ROOT
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
MIGRATIONS = ROOT / "migrations"
ARTIFACTS = STATIC / "artifacts"


def create_app(
    database_url: str | None = None,
    *,
    secret_key: str | None = None,
) -> App:
    """Build an isolated Showrun application for production or tests."""

    config = AppConfig.from_env(
        template_dir=TEMPLATES,
        static_dir=STATIC,
        debug=os.environ.get("CHIRP_ENV", "development") == "development",
        alpine=True,
        csp_nonce_enabled=True,
        htmx=False,
        safe_target=False,
        sse_lifecycle=False,
        worker_mode="async",
        workers=1,
        max_request_body_size=2_621_440,
        max_upload_size=2_097_152,
        rate_limit_enabled=True,
        rate_limit_requests_per_second=20,
        rate_limit_burst=60,
    )
    if secret_key:
        config = replace(config, secret_key=secret_key)
    if not config.secret_key:
        config = replace(config, secret_key="showrun-local-signing-key-change-in-production")

    resolved_database_url = database_url or os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{Path.cwd() / 'showrun.db'}",
    )
    application = App(config, db=resolved_database_url, migrations=str(MIGRATIONS))
    register_markdown_filter(application)
    # Chirp owns the nonce-protected Alpine runtime. Keep the remaining
    # production headers without appending a second, conflicting CSP policy.
    headers = SecurityHeadersConfig(content_security_policy=None)
    store = ShowrunStore(application.db)
    community = CommunityStore(application.db)
    questions = QuestionsStore(application.db)
    auth = AuthConfig(
        load_user=store.get_user,
        verify_token=lambda token: verify_api_token(store, token),
        login_url="/login",
    )
    csrf = CSRFConfig(exempt_paths=frozenset({"/api/v1/imports", "/api/v1/events"}))
    # Run outermost so the public embed exception is applied after Chirp's
    # nonce CSP and secure-by-default X-Frame-Options middleware.
    application.add_middleware(PublicEmbedPolicy())
    for middleware in secure_stack(application.config, auth=auth, csrf=csrf, headers=headers):
        application.add_middleware(middleware)

    @application.on_startup
    async def seed_golden_showrun() -> None:
        golden = load_artifact(
            ARTIFACTS / "showrun-session.jsonl",
            ARTIFACTS / "showrun-lesson.tape",
        )
        await sync_golden(store, golden)
        await store.publish("lesson_golden", "public")

    ShowrunRoutes(application, store, community, questions).register()
    return application
