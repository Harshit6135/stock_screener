import sqlite3
from datetime import date
from uuid import uuid4

from flask import Flask

from src.application.catalog import ArtifactCatalog
from src.application.legacy_portfolio import LegacyPortfolioImporter
from src.application.legacy_portfolio_web import create_legacy_portfolio_blueprint
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.execution_gateway import Ledger
from src.platform_kernel import ArtifactStore


def _legacy(path, symbol="ABC"):
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE investment_holdings (
            symbol TEXT, date TEXT, entry_date TEXT, entry_price NUMERIC,
            avg_price NUMERIC, units INTEGER);
           CREATE TABLE investment_summary (date TEXT, remaining_capital NUMERIC);
           CREATE TABLE capital_events (
             id INTEGER PRIMARY KEY, date TEXT, amount NUMERIC,
             event_type TEXT, note TEXT);
           CREATE TABLE actions (
             action_id TEXT PRIMARY KEY, action_date TEXT, type TEXT,
             reason TEXT, symbol TEXT, risk NUMERIC, atr NUMERIC,
             units INTEGER, prev_close NUMERIC, execution_price NUMERIC,
             capital NUMERIC, status TEXT, buy_cost NUMERIC,
             sell_cost NUMERIC, tax NUMERIC);"""
    )
    connection.execute(
        "INSERT INTO investment_holdings VALUES (?, '2026-09-07', '2026-09-01', 100, 110, 2)",
        (symbol,),
    )
    connection.execute("INSERT INTO investment_summary VALUES ('2026-09-07', 500)")
    connection.execute(
        "INSERT INTO capital_events VALUES (1, '2025-12-10', 1000, 'initial', 'seed')"
    )
    connection.execute(
        "INSERT INTO capital_events VALUES (2, '2026-01-02', -5, 'realized_gain', 'sale')"
    )
    connection.execute(
        """INSERT INTO actions VALUES
           ('action-1', '2026-01-02', 'sell', 'review', ?, 1, 1, 1,
            110, 108, 108, 'Approved', 0, 0, 1)""",
        (symbol,),
    )
    connection.commit()
    connection.close()


def test_preview_and_import_preserve_cash_and_cost_basis(tmp_path):
    database, legacy = tmp_path / "system.db", tmp_path / "personal.db"
    _legacy(legacy)
    market = MarketRepository(database)
    market.upsert_instruments(
        [TrackedInstrument(str(uuid4()), "INE000000001", "ABC", "NSE", "42", date(2026, 9, 1))]
    )
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    ledger = Ledger(database)
    importer = LegacyPortfolioImporter(database, market, ledger, publisher)
    preview = importer.preview({"legacy_path": str(legacy)})
    assert preview["unresolved_symbols"] == []
    assert preview["opening_cash_required"] == "720"
    assert preview["source_realised_gain_total"] == "-5"
    assert len(preview["source_capital_events"]) == 2
    assert preview["source_approved_action_count"] == 1
    assert preview["source_actions"][0]["execution_price"] == "108"
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "test-secret"
    app.register_blueprint(create_legacy_portfolio_blueprint(importer))
    client, headers = app.test_client(), {"X-Operator-Token": "test-secret"}
    assert (
        client.post(
            "/api/v2/portfolio/import-v3/preview", json={"legacy_path": str(legacy)}
        ).status_code
        == 401
    )
    imported = client.post(
        "/api/v2/portfolio/import-v3",
        json={"account_id": "legacy-paper", "legacy_path": str(legacy)},
        headers=headers,
    )
    assert imported.status_code == 201
    projection = ledger.projection("legacy-paper")
    assert str(projection.cash.amount) == "500"
    assert projection.open_lots[0].unit_cost.amount == 110
    _, imported_artifact = publisher.store.read_json(
        "imports/legacy_portfolio", imported.json["artifact_id"]
    )
    assert imported_artifact["source_realised_gain_total"] == "-5"
    assert (
        client.post(
            "/api/v2/portfolio/import-v3",
            json={"account_id": "legacy-paper", "legacy_path": str(legacy)},
            headers=headers,
        ).status_code
        == 201
    )


def test_import_refuses_unresolved_symbols(tmp_path):
    database, legacy = tmp_path / "system.db", tmp_path / "personal.db"
    _legacy(legacy, "MISSING")
    market = MarketRepository(database)
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    importer = LegacyPortfolioImporter(database, market, Ledger(database), publisher)
    preview = importer.preview({"legacy_path": str(legacy)})
    assert preview["unresolved_symbols"] == ["MISSING"]
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "test-secret"
    app.register_blueprint(create_legacy_portfolio_blueprint(importer))
    response = app.test_client().post(
        "/api/v2/portfolio/import-v3",
        json={"account_id": "legacy-paper", "legacy_path": str(legacy)},
        headers={"X-Operator-Token": "test-secret"},
    )
    assert response.status_code == 409
