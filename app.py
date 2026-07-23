"""Showrun: directed visual demos, built with the Chirp stack."""

from __future__ import annotations

import os
from pathlib import Path

from chirp.app import App
from chirp.config import AppConfig
from chirp.ext.chirp_ui import use_chirp_ui
from chirp.markdown import register_markdown_filter
from chirp.templating.returns import Page

from showrun_artifacts import load_artifact

ROOT = Path(__file__).parent
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
ARTIFACTS = STATIC / "artifacts"


def create_app() -> App:
    """Create an isolated Showrun application."""

    artifact = load_artifact(
        ARTIFACTS / "showrun-session.jsonl",
        ARTIFACTS / "showrun-lesson.tape",
    )
    config = AppConfig.from_env(
        template_dir=TEMPLATES,
        static_dir=STATIC,
        debug=os.environ.get("CHIRP_ENV", "development") == "development",
        htmx=True,
        workers=1,
    )
    application = App(config)
    use_chirp_ui(application)
    register_markdown_filter(application)

    @application.route("/", name="home")
    async def index() -> Page:
        return Page(
            "index.html",
            "page_root",
            title=artifact.title,
            events=artifact.events,
            chapters=artifact.chapters,
            duration=artifact.duration,
            player_config=artifact.player_config(),
            outputs=artifact.outputs,
        )

    return application


app = create_app()


if __name__ == "__main__":
    port = os.environ.get("PORT")
    if port:
        app.run(host="0.0.0.0", port=int(port))
    else:
        app.run()
