import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from flask import Flask

from src.domains.portfolio_accounting import Ledger, OpeningPosition
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.http.tradebook import create_tradebook_blueprint
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.gates.workflows.tradebook_import import TradebookImport
from src.platform_kernel import Money, Quantity

CSV = b"""symbol,isin,trade_date,exchange,segment,trade_type,quantity,price,trade_id,order_execution_time
ABC,ISINABC,2026-07-01,NSE,EQ,buy,10,10,1,2026-07-01T09:30:00
ABC,ISINABC,2026-08-01,NSE,EQ,buy,10,20,2,2026-08-01T09:30:00
ABC,ISINABC,2026-09-01,NSE,EQ,sell,12,25,3,2026-09-01T09:30:00
CLOSED,ISINCLOSED,2026-07-01,NSE,EQ,buy,6,5,4,2026-07-01T09:30:00
CLOSED,ISINCLOSED,2026-08-01,NSE,EQ,sell,6,7,5,2026-08-01T09:30:00
IGNORED,ISINIGNORE,2026-07-01,NSE,EQ,buy,4,100,6,2026-07-01T09:30:00
"""


def fixture_app(tmp_path):
    database = tmp_path / "portfolio.db"
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("account", Money("500"))
    market.upsert_instruments(
        [TrackedInstrument("abc", "ISINABC", "ABC", "NSE", "1", date(2026, 1, 1))]
    )
    at = datetime.now(UTC)
    ledger.import_opening_positions(
        "account",
        "opening",
        0,
        [
            OpeningPosition(
                "abc",
                at.date(),
                Quantity(8),
                Money("18"),
                at,
                json.dumps({"source": "kite-opening-balance", "broker_account_id": "account"}),
            )
        ],
    )
    ledger.fund_broker_imports("account", "account")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.register_blueprint(create_tradebook_blueprint(TradebookImport(database, ledger, market)))
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    return app.test_client(), ledger


def test_csv_preview_and_open_only_apply_are_scoped_and_idempotent(tmp_path):
    client, ledger = fixture_app(tmp_path)
    root = "/api/portfolio/accounts/account/tradebook"
    preview = client.post(root + "/preview", data={"file": (io.BytesIO(CSV), "tradebook.csv")})
    assert preview.status_code == 200
    data = preview.json
    assert data["closed_symbols"] == 1
    assert data["ignored_open_symbols"] == 1
    assert data["holdings"][0]["lots"] == [
        {"date": "2026-08-01", "units": 8, "unit_cost": "20", "trade_id": "2"}
    ]
    assert ledger.projection("account").cash.amount == 356
    command = {
        "upload_id": data["upload_id"],
        "expected_version": data["expected_version"],
        "selected_instrument_ids": ["abc"],
    }
    applied = client.post(root + "/apply", json=command)
    assert applied.status_code == 200
    assert applied.json["closed_trades_imported"] == 0
    assert applied.json["cash_adjustment"] == "-16"
    projection = ledger.projection("account")
    assert projection.cash.amount == 340
    assert projection.realised_pnl.amount == 0
    assert projection.open_lots[0].opened_on == date(2026, 8, 1)
    assert projection.open_lots[0].unit_cost.amount == 20
    valuation_date = datetime.now(UTC).date()
    MarketRepository(ledger.path).upsert_bars(
        "abc", [NormalizedBar("abc", valuation_date, 25, 25, 25, 25, 100)], "test"
    )
    valuation = client.get(
        f"/api/portfolio/accounts/account/valuation?as_of_date={valuation_date}"
    ).json
    expected_return = (Decimal(25) / 20) ** (
        Decimal(365) / Decimal((valuation_date - date(2026, 8, 1)).days)
    ) - 1
    assert abs(Decimal(valuation["holdings_xirr"]) - expected_return) < Decimal("1e-9")
    assert valuation["xirr"] is None  # Recovered buys predate account cash history.
    assert valuation["cash"] == "340"
    assert client.post(root + "/apply", json=command).json == applied.json
    assert ledger.projection("account").cash.amount == 340
    ledger.open_account("other", Money("100"))
    assert (
        client.post("/api/portfolio/accounts/other/tradebook/apply", json=command).status_code
        == 400
    )
    command["account_id"] = "wrong"
    assert client.post(root + "/apply", json=command).status_code == 400


def test_mismatched_quantity_and_stale_portfolio_are_rejected(tmp_path):
    client, ledger = fixture_app(tmp_path)
    root = "/api/portfolio/accounts/account/tradebook"
    mismatch = CSV.replace(b"sell,12,25", b"sell,11,25")
    preview = client.post(
        root + "/preview", data={"file": (io.BytesIO(mismatch), "tradebook.csv")}
    ).json
    assert preview["holdings"][0]["eligible"] is False
    command = {
        "upload_id": preview["upload_id"],
        "expected_version": preview["expected_version"],
        "selected_instrument_ids": ["abc"],
    }
    assert client.post(root + "/apply", json=command).status_code == 400
    preview = client.post(root + "/preview", data={"file": (io.BytesIO(CSV), "tradebook.csv")}).json
    ledger.record_cash_transfer("account", "deposit", 2, "DEPOSIT", Money("10"), reason="test")
    command.update(upload_id=preview["upload_id"], expected_version=preview["expected_version"])
    assert client.post(root + "/apply", json=command).status_code == 400
    assert ledger.projection("account").cash.amount == Decimal(366)


def test_csv_upload_can_exceed_default_json_request_limit(tmp_path):
    client, _ = fixture_app(tmp_path)
    lines = CSV.splitlines(keepends=True)
    large = lines[0] + b"".join(lines[1:]) * 200
    assert len(large) > 64 * 1024
    response = client.post(
        "/api/portfolio/accounts/account/tradebook/preview",
        data={"file": (io.BytesIO(large), "tradebook.csv")},
    )
    assert response.status_code == 200
    assert response.json["trade_count"] == 6
    assert response.json["duplicate_rows"] == 6 * 199


def test_unrelated_unresolved_sells_do_not_block_selected_open_holdings(tmp_path):
    client, ledger = fixture_app(tmp_path)
    raw = CSV + b"MISSING,OTHER,2026-09-01,NSE,EQ,sell,100,10,unknown,2026-09-01T09:30:00\n"
    response = client.post(
        "/api/portfolio/accounts/account/tradebook/preview",
        data={"file": (io.BytesIO(raw), "tradebook.csv")},
    )
    assert response.status_code == 200
    assert response.json["holdings"][0]["eligible"] is True
    assert response.json["unresolved_symbols"][0]["symbol"] == "MISSING"
    assert ledger.projection("account").cash.amount == 356
