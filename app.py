"""Railway and local entry point for the Showrun web application."""

from showrun.web import create_app

app = create_app()


if __name__ == "__main__":
    app.run()
