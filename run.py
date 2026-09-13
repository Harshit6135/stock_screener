import os
from pathlib import Path

from flask import Flask, jsonify
from waitress import serve

from src.application.composition import ApplicationServices
from src.application.operations import sqlite_ready
from src.application.runtime import RuntimeConfig
from src.application.web import create_operations_blueprint


def create_app(config_class=RuntimeConfig):
    """Build the backend-only composition layer.

    Domain state is held in durable application stores, not Flask-SQLAlchemy
    metadata.  Database creation is performed by reviewed store migrations,
    never by a web-process-wide ``create_all`` side effect.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)
    data_directory = Path(app.config["DATA_DIRECTORY"])
    if not data_directory.is_absolute():
        data_directory = Path(app.root_path) / data_directory
    data_directory.mkdir(parents=True, exist_ok=True)
    app.config["DATA_DIRECTORY"] = data_directory
    services = ApplicationServices.create(data_directory)
    app.extensions["screener_services"] = services
    app.register_blueprint(create_operations_blueprint(services.jobs))

    @app.get("/health/live")
    def liveness():
        """Process liveness only; provider connectivity is intentionally excluded."""
        return jsonify({"status": "ok"}), 200

    @app.get("/health/ready")
    def readiness():
        """Readiness requires the durable operations store to accept a query."""
        if not sqlite_ready(app.extensions["screener_services"].database):
            return jsonify({"status": "not-ready"}), 503
        return jsonify({"status": "ready"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    import logging

    from paste.translogger import TransLogger

    # Waitress's internal logs
    logging.getLogger("waitress").setLevel(logging.INFO)

    # TransLogger captures HTTP requests and prints them to console
    logged_app = TransLogger(app, setup_console_handler=False)

    host = os.environ.get("SCREENER_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "::1", "localhost"} and os.environ.get("SCREENER_ALLOW_NETWORK_BIND") != "true":
        raise RuntimeError("non-loopback binding requires SCREENER_ALLOW_NETWORK_BIND=true and a TLS-capable reverse proxy")
    print(f"Starting Waitress server on http://{host}:5000 ...")

    serve(
        logged_app,
        host=host,
        port=5000,
        threads=3,  # SSE stream + pipeline + dashboard run concurrently
        channel_timeout=600,  # keep SSE connections alive up to 10 min
    )
