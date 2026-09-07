from app import create_app

app = create_app()

if __name__ == "__main__":
    if not app.config.get("DEBUG"):
        raise SystemExit(
            "Refusing to run the Werkzeug development server outside DEBUG "
            "mode - it has no protection against untrusted traffic and, "
            "with DEBUG on, an unauthenticated interactive Python debugger. "
            "Serve production with a real WSGI server instead, e.g.:\n"
            "  uv run gunicorn -w 4 -b 0.0.0.0:8000 main:app"
        )
    app.run()
