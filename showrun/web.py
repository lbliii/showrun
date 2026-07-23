"""Application factory for Showrun's persistent web product."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from chirp.app import App
from chirp.config import AppConfig
from chirp.markdown import register_markdown_filter
from chirp.middleware.security_headers import SecurityHeadersConfig
from chirp.middleware.stack import secure_stack

from showrun.artifacts import load_artifact
from showrun.routes import LOCAL_TOKEN, ShowrunRoutes
from showrun.store import ShowrunStore

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"
MIGRATIONS = ROOT / "migrations"
ARTIFACTS = STATIC / "artifacts"


def create_app(
    database_url: str | None = None,
    *,
    admin_token: str | None = None,
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
    )
    if secret_key:
        config = replace(config, secret_key=secret_key)
    if not config.secret_key:
        config = replace(config, secret_key="showrun-local-signing-key-change-in-production")

    resolved_token = admin_token or os.environ.get("SHOWRUN_ADMIN_TOKEN")
    if not resolved_token:
        if config.env != "development":
            raise RuntimeError("SHOWRUN_ADMIN_TOKEN is required outside development")
        resolved_token = LOCAL_TOKEN

    resolved_database_url = database_url or os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{ROOT / 'showrun.db'}",
    )
    application = App(config, db=resolved_database_url, migrations=str(MIGRATIONS))
    register_markdown_filter(application)
    # Chirp owns the nonce-protected Alpine runtime. Keep the remaining
    # production headers without appending a second, conflicting CSP policy.
    headers = SecurityHeadersConfig(content_security_policy=None)
    for middleware in secure_stack(application.config, headers=headers):
        application.add_middleware(middleware)

    store = ShowrunStore(application.db)

    @application.on_startup
    async def seed_golden_showrun() -> None:
        golden = load_artifact(
            ARTIFACTS / "showrun-session.jsonl",
            ARTIFACTS / "showrun-lesson.tape",
        )
        await store.seed_golden(golden)
        await store.publish("lesson_golden", "public")

    ShowrunRoutes(application, store, resolved_token).register()
    return application
