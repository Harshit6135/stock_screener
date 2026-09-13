import os
from pathlib import Path

from flask import Flask, jsonify, redirect
from waitress import serve  # type: ignore[import-untyped]

from src.application.actions_web import create_actions_blueprint
from src.application.backtest_web import create_backtest_blueprint
from src.application.broker_web import create_broker_blueprint
from src.application.composition import ApplicationServices
from src.application.compatibility_web import create_compatibility_blueprint
from src.application.configs_web import create_configs_blueprint
from src.application.dashboard_web import create_dashboard_blueprint
from src.application.kite_auth import KiteAuthService, load_kite_credentials
from src.application.kite_web import create_kite_auth_blueprint
from src.application.legacy_portfolio_web import create_legacy_portfolio_blueprint
from src.application.market_web import create_market_blueprint
from src.application.operations import sqlite_ready
from src.application.pipeline_web import create_pipeline_blueprint
from src.application.portfolio_web import create_portfolio_blueprint
from src.application.reference_web import create_reference_blueprint
from src.application.research_web import create_research_blueprint
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
        data_directory = Path.cwd() / data_directory
    data_directory.mkdir(parents=True, exist_ok=True)
    app.config["DATA_DIRECTORY"] = data_directory

    def resolved_token_path(config_key: str, default: str) -> Path:
        path = Path(app.config.get(config_key, default))
        return path if path.is_absolute() else Path.cwd() / path

    market_data_token_path = resolved_token_path(
        "MARKET_DATA_KITE_ACCESS_TOKEN_PATH", "access_token.txt"
    )
    portfolio_token_path = resolved_token_path(
        "PORTFOLIO_KITE_ACCESS_TOKEN_PATH", "portfolio_access_token.txt"
    )
    market_data_credentials = load_kite_credentials(app.config, profile="market_data")
    portfolio_credentials = load_kite_credentials(app.config, profile="portfolio")
    services = ApplicationServices.create(
        data_directory,
        market_data_kite_credentials=market_data_credentials,
        market_data_kite_token_path=market_data_token_path,
        portfolio_kite_credentials=portfolio_credentials,
        portfolio_kite_token_path=portfolio_token_path,
        portfolio_live_execution=bool(app.config.get("PORTFOLIO_KITE_LIVE_EXECUTION", False)),
        nse_csv_path=Path.cwd() / "data" / "imports" / "NSE.csv",
        bse_csv_path=Path.cwd() / "data" / "imports" / "BSE.csv",
        legacy_market_path=Path.cwd() / "instance" / "market_data.db",
    )
    app.extensions["screener_services"] = services
    app.register_blueprint(create_dashboard_blueprint())
    app.register_blueprint(
        create_operations_blueprint(
            services.jobs,
            services.worker.handlers.keys(),
            worker=services.worker,
            background_worker=services.background_worker,
        )
    )
    if (
        os.environ.get("SCREENER_RUN_WORKER", "true").lower() in {"1", "true", "yes"}
        and services.background_worker is not None
    ):
        services.background_worker.start()
    app.register_blueprint(create_reference_blueprint(services.artifacts, services.market, services.publisher))
    app.register_blueprint(create_market_blueprint(services.market, services.catalog, services.index_poller, services.market_refresh, services.corporate_actions, services.intraday_alerts, services.intraday_stream))
    app.register_blueprint(create_research_blueprint(services.artifacts, services.research, services.jobs))
    app.register_blueprint(create_pipeline_blueprint(services.pipelines))
    app.register_blueprint(create_configs_blueprint(services.configs))
    app.register_blueprint(create_portfolio_blueprint(services.ledger, services.market))
    app.register_blueprint(create_broker_blueprint(services.broker_orders))
    app.register_blueprint(create_legacy_portfolio_blueprint(services.legacy_portfolio))
    app.register_blueprint(create_backtest_blueprint(services.backtests, services.artifacts))
    app.register_blueprint(create_actions_blueprint(services.actions))
    app.register_blueprint(create_compatibility_blueprint(services))

    @app.get("/")
    def legacy_dashboard_root():
        return redirect("/app")

    @app.get("/dashboard")
    def legacy_dashboard():
        from flask import render_template
        return render_template("dashboard.html")

    app.register_blueprint(
        create_kite_auth_blueprint(
            KiteAuthService(market_data_credentials, market_data_token_path)
            if market_data_credentials is not None
            else None,
            KiteAuthService(portfolio_credentials, portfolio_token_path)
            if portfolio_credentials is not None
            else None,
        )
    )

    @app.get("/health/live")
    def liveness():
        """Process liveness only; provider connectivity is intentionally excluded."""
        return jsonify({"status": "ok"}), 200

    @app.get("/health/ready")
    def readiness():
        """Readiness requires the durable operations store to accept a query."""
        if not sqlite_ready(
            app.extensions["screener_services"].database,
            (
                "catalog",
                "ops",
                "ledger",
                "market",
                "research",
                "strategy_configs",
                "backtest",
                "actions",
                "legacy_portfolio_import",
                "research_pipeline",
            ),
        ):
            return jsonify({"status": "not-ready"}), 503
        return jsonify({"status": "ready"}), 200

    return app


def main() -> None:
    """Run the local production WSGI server."""
    import logging

    # Waitress's internal logs
    logging.getLogger("waitress").setLevel(logging.INFO)

    host = os.environ.get("SCREENER_HOST", "127.0.0.1")
    if (
        host not in {"127.0.0.1", "::1", "localhost"}
        and os.environ.get("SCREENER_ALLOW_NETWORK_BIND") != "true"
    ):
        raise RuntimeError(
            "non-loopback binding requires SCREENER_ALLOW_NETWORK_BIND=true and a TLS-capable reverse proxy"
        )
    print(f"Starting Waitress server on http://{host}:5000 ...")

    serve(
        create_app(),
        host=host,
        port=5000,
        threads=3,  # SSE stream + pipeline + dashboard run concurrently
        channel_timeout=600,  # keep SSE connections alive up to 10 min
    )


if __name__ == "__main__":
    main()
