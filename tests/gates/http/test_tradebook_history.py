import io
import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from flask import Flask

from src.domains.portfolio_accounting import Ledger
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.http.tradebook import create_tradebook_blueprint
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.gates.workflows.corporate_actions import CorporateActions
from src.gates.workflows.portfolio_sync import PortfolioSync
from src.gates.workflows.tradebook_import import TradebookImport
from src.platform_kernel import DomainValidationError, Money
from src.platform_kernel.sqlite import sqlite_connection

CSV = b"""symbol,isin,trade_date,exchange,trade_type,quantity,price,trade_id,charges
ABC,ISINABC,2026-02-09,NSE,buy,10,10,1,2
ABC,ISINABC,2026-05-01,NSE,sell,4,20,2,1
DEF,ISINDEF,2026-03-01,NSE,buy,2,50,3,0
DEF,ISINDEF,2026-04-01,NSE,sell,2,40,4,1
"""


def test_kite_refresh_after_full_history_updates_only_prices(tmp_path):
    client, ledger, market = fixture(tmp_path)
    client.post("/api/portfolio/accounts/account/tradebook/apply", json=command(preview(client)))
    before = ledger.projection("account")

    class Broker:
        def holdings(self):
            return [
                {
                    "tradingsymbol": "ABC",
                    "isin": "ISINABC",
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": 7,
                    "instrument_token": 1,
                    "average_price": 10,
                    "last_price": 25,
                },
                {
                    "tradingsymbol": "NEW",
                    "isin": "ISINNEW",
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": 2,
                    "instrument_token": 2,
                    "average_price": 10,
                    "last_price": 25,
                },
            ]

        def positions(self):
            return {"net": []}

    class Accounts:
        def validate(self, account_id):
            return None

        def client(self, account_id):
            return Broker()

    sync = PortfolioSync(ledger.path, Accounts(), ledger, market)
    assert sync.preview_holdings("account")["history_mode"] is True
    result = sync.import_holdings("account")
    assert result["imported_positions"] == 0
    assert result["quantity_mismatches"] == ["ABC"]
    assert ledger.projection("account") == before
    assert len(ledger.events("account")) == 4


def test_unmapped_bse_bond_does_not_block_other_holdings_or_enter_ledger(tmp_path):
    _client, ledger, market = fixture(tmp_path)

    class Broker:
        def holdings(self):
            return [
                {
                    "tradingsymbol": "ABC",
                    "isin": "ISINABC",
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": 2,
                    "instrument_token": 1,
                    "average_price": 10,
                    "last_price": 15,
                },
                {
                    "tradingsymbol": "SGBDE31III",
                    "isin": "ISINSGB",
                    "exchange": "BSE",
                    "product": "CNC",
                    "quantity": 1,
                    "instrument_token": 2,
                    "average_price": 6000,
                    "last_price": 12000,
                },
            ]

        def positions(self):
            return {"net": []}

    class Accounts:
        def validate(self, account_id):
            return None

        def client(self, account_id):
            return Broker()

    sync = PortfolioSync(ledger.path, Accounts(), ledger, market)
    review = sync.preview_holdings("account")
    bond = next(h for h in review["holdings"] if h["broker_symbol"] == "SGBDE31III")
    assert bond["eligible"] is False
    assert ledger.events("account") == []
    stock = next(h for h in review["holdings"] if h["broker_symbol"] == "ABC")
    result = sync.import_holdings("account", [stock["instrument_id"]])
    assert result["imported_positions"] == 1
    assert result["ignored_count"] == 1
    assert ledger.projection("account").cash.amount == 280
    assert len(ledger.projection("account").open_lots) == 1
    assert all(i["symbol"] != "SGBDE31III" for i in market.tracked_instruments())


def test_same_day_sells_are_averaged_across_executions_and_fifo_buy_lots(tmp_path):
    client, ledger, _market = fixture(tmp_path)
    csv = b"symbol,isin,trade_date,exchange,trade_type,quantity,price,trade_id\nABC,ISINABC,2026-02-09,NSE,buy,5,10,1\nABC,ISINABC,2026-03-09,NSE,buy,5,20,2\nABC,ISINABC,2026-05-01,NSE,sell,4,20,3\nABC,ISINABC,2026-05-01,NSE,sell,3,30,4\nABC,ISINABC,2026-05-01,NSE,sell,3,10,5\n"
    review = preview(client, csv)
    assert (
        client.post(
            "/api/portfolio/accounts/account/tradebook/apply", json=command(review)
        ).status_code
        == 200
    )
    before = ledger.projection("account")
    rows = client.get("/api/portfolio/accounts/account/journal").json["journal"]
    assert len(rows) == 1
    assert rows[0]["units"] == 10
    assert Decimal(rows[0]["buy_price"]) == 15
    assert Decimal(rows[0]["sell_price"]) == 20
    assert Decimal(rows[0]["realised_pnl"]) == 50
    assert rows[0]["buy_date"] == "2026-02-09"
    assert rows[0]["buy_date_end"] == "2026-03-09"
    assert ledger.projection("account") == before


def fixture(tmp_path):
    database = tmp_path / "history.db"
    ledger, market = Ledger(database), MarketRepository(database)
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    app.register_blueprint(create_tradebook_blueprint(TradebookImport(database, ledger, market)))
    client = app.test_client()
    assert (
        client.post(
            "/api/portfolio/accounts",
            json={"account_id": "account", "opening_date": "2026-02-01", "opening_cash": "300"},
        ).status_code
        == 201
    )
    return client, ledger, market


def preview(client, csv=CSV):
    response = client.post(
        "/api/portfolio/accounts/account/tradebook/preview",
        data={"mode": "history", "file": (io.BytesIO(csv), "trades.csv")},
    )
    assert response.status_code == 200, response.json
    return response.json


def command(review):
    return {
        "mode": "history",
        "upload_id": review["upload_id"],
        "expected_version": review["expected_version"],
        "selected_instrument_ids": [h["instrument_id"] for h in review["holdings"]],
    }


def test_complete_history_cash_realised_unrealised_xirr_and_cagr(tmp_path):
    client, ledger, market = fixture(tmp_path)
    review = preview(client)
    assert review["closed_symbols"] == 1
    assert review["summary"]["realised_pnl"] == "17.2"
    assert ledger.accounts()[0]["version"] == 0
    applied = client.post("/api/portfolio/accounts/account/tradebook/apply", json=command(review))
    assert applied.status_code == 200, applied.json
    assert applied.json["imported_trades"] == 4
    assert applied.json["cash"] == "256"
    instrument_id = next(h["instrument_id"] for h in review["holdings"] if h["symbol"] == "ABC")
    market.upsert_bars(
        instrument_id,
        [NormalizedBar(instrument_id, date(2026, 10, 6), 25, 25, 25, 25, 100)],
        "valuation",
    )
    value = client.get("/api/portfolio/accounts/account/valuation?as_of_date=2026-10-06").json
    assert Decimal(value["realised_pnl"]) == Decimal("17.2")
    assert Decimal(value["unrealised_gain"]) == Decimal("88.8")
    assert Decimal(value["net_gain"]) == 106
    assert Decimal(value["equity"]) == 406
    expected = (Decimal(406) / 300) ** (
        Decimal(365) / (date(2026, 10, 6) - date(2026, 2, 1)).days
    ) - 1
    assert abs(Decimal(value["xirr"]) - expected) < Decimal("1e-10")
    assert abs(Decimal(value["annualized_return"]) - expected) < Decimal("1e-10")
    assert value["fees_note"] is None
    assert Decimal(value["total_return"]) == Decimal(106) / 300
    assert Decimal(value["recorded_charges"]) == Decimal(4)
    assert Decimal(value["tax_estimates"][0]["estimated_tax"]) == Decimal("8.32")
    # Sold lots: ABC cost 40.8 -> net proceeds 79; DEF cost 100 -> 79.
    from src.domains.portfolio_accounting.portfolio_performance import calculate_xirr

    closed_return = calculate_xirr([
        (date(2026, 2, 9), Decimal("-40.8")),
        (date(2026, 5, 1), Decimal(79)),
        (date(2026, 3, 1), Decimal(-100)),
        (date(2026, 4, 1), Decimal(79)),
    ])
    assert abs(Decimal(value["realised_xirr"]) - closed_return) < Decimal("1e-10")
    with patch("src.gates.http.portfolio.portfolio_stops", return_value={
        instrument_id: {"current_trailing_stop": Decimal(30)}
    }):
        risk_value = client.get(
            "/api/portfolio/accounts/account/valuation?as_of_date=2026-10-06"
        ).json
    assert Decimal(risk_value["capital_risk"]) == Decimal("61.2") - 180
    assert Decimal(risk_value["stop_based_risk"]) == 0
    assert Decimal(risk_value["portfolio_risk"]) == 0
    assert sum(Decimal(t["realised_pnl"]) for t in ledger.journal("account")) == Decimal("17.2")
    # Same file and overlapping exports cannot double count fills.
    assert (
        client.post(
            "/api/portfolio/accounts/account/tradebook/apply", json=command(preview(client))
        ).json
        == applied.json
    )
    overlapping = CSV + b"ABC,ISINABC,2026-06-01,NSE,buy,1,10,5,0\n"
    result = client.post(
        "/api/portfolio/accounts/account/tradebook/apply",
        json=command(preview(client, overlapping)),
    )
    assert result.status_code == 200, result.json
    assert result.json["imported_trades"] == 1
    assert result.json["duplicate_trades"] == 4
    assert len(ledger.events("account")) == 5


def test_verified_split_replays_realised_history_and_dated_projection(tmp_path):
    client, ledger, market = fixture(tmp_path)
    ledger.open_account(
        "split",
        Money("30000"),
        date(2026, 2, 1),
    )
    market.upsert_instruments(
        [TrackedInstrument("mwl", "INE0JYY01029", "MWL", "NSE", "1", date(2026, 1, 1))]
    )
    CorporateActions(ledger.path, market).detect_events(
        [
            {
                "symbol": "MWL",
                "isin": "INE0JYY01011",
                "ex_date": "2026-07-10",
                "action_type": "SPLIT",
                "ratio": "1:10",
            }
        ]
    )
    csv = b"symbol,isin,trade_date,exchange,trade_type,quantity,price,trade_id\nMWL,INE0JYY01011,2026-05-25,NSE,buy,60,370,1\nMWL,INE0JYY01029,2026-07-21,BSE,sell,600,36.3,2\n"
    review = client.post(
        "/api/portfolio/accounts/split/tradebook/preview",
        data={"mode": "history", "file": (io.BytesIO(csv), "trades.csv")},
    ).json
    applied = client.post("/api/portfolio/accounts/split/tradebook/apply", json=command(review))
    assert applied.status_code == 200, applied.json
    assert applied.json["corporate_actions"] == 1
    assert applied.json["realised_pnl"] == "-420.0"
    assert not ledger.projection("split").open_lots
    assert ledger.projection_at("split", date(2026, 7, 9)).open_lots[0].remaining_units.units == 60
    assert (
        ledger.projection_at("split", date(2026, 7, 10)).open_lots[0].remaining_units.units == 600
    )
    assert ledger.journal("split")[0]["buy_price"] == "37"


def test_dates_unresolved_history_and_stale_apply_do_not_mutate(tmp_path):
    client, ledger, _ = fixture(tmp_path)
    before = CSV.replace(b"2026-02-09", b"2026-01-09")
    review = preview(client, before)
    assert not next(h for h in review["holdings"] if h["symbol"] == "ABC")["eligible"]
    assert (
        client.post(
            "/api/portfolio/accounts/account/tradebook/apply", json=command(review)
        ).status_code
        == 400
    )
    review = preview(client)
    payload = command(review)
    payload["expected_version"] = 99
    assert (
        client.post("/api/portfolio/accounts/account/tradebook/apply", json=payload).status_code
        == 400
    )
    assert ledger.accounts()[0]["version"] == 0
    assert (
        client.post(
            "/api/portfolio/accounts",
            json={"account_id": "bad", "opening_cash": "300", "opening_date": "not a date"},
        ).status_code
        == 400
    )


def test_old_preview_can_refresh_from_exchange_without_importing_or_changing_trade_identity(
    tmp_path,
):
    client, ledger, market = fixture(tmp_path)
    CorporateActions(ledger.path, market).detect_events(
        [
            {
                "symbol": "MWL",
                "isin": "INE0JYY01011",
                "ex_date": "2026-07-10",
                "action_type": "SPLIT",
                "ratio": "1:10",
            }
        ]
    )
    raw = b"symbol,isin,trade_date,trade_type,quantity,price,trade_id\nMWL,INE0JYY01011,2026-03-01,buy,2,100,1\nMWL,INE0JYY01029,2026-08-01,sell,20,12,2\n"
    review = preview(client, raw)
    with sqlite_connection(ledger.path) as connection:
        archived = json.loads(
            connection.execute("SELECT parsed_json FROM tradebook_uploads").fetchone()[0]
        )
        original_trades = archived["trades"]
        archived["corporate_action_adjustments"][0].pop("event_id")
        archived.pop("corporate_actions")
        connection.execute("UPDATE tradebook_uploads SET parsed_json=?", (json.dumps(archived),))
    root = "/api/portfolio/accounts/account/tradebook"
    assert client.post(root + "/apply", json=command(review)).status_code == 400
    response = client.post(
        root + "/refresh-preview", json={"upload_id": review["upload_id"], "mode": "history"}
    )
    assert response.status_code == 200, response.json
    refreshed = response.json
    assert refreshed["upload_id"] == review["upload_id"]
    assert refreshed["corporate_action_adjustments"][0]["event_id"]
    assert ledger.events("account") == []
    with sqlite_connection(ledger.path, read_only=True) as connection:
        archived = json.loads(
            connection.execute("SELECT parsed_json FROM tradebook_uploads").fetchone()[0]
        )
    assert archived["trades"] == original_trades
    applied = client.post(root + "/apply", json=command(refreshed))
    assert applied.status_code == 200, applied.json
    assert Decimal(applied.json["realised_pnl"]) == 40


def test_kite_direct_import_after_history_preserves_trades_and_saves_purchase_dates(tmp_path):
    client, ledger, market = fixture(tmp_path)
    client.post("/api/portfolio/accounts/account/tradebook/apply", json=command(preview(client)))
    original_events, original_journal = ledger.events("account"), ledger.journal("account")

    class Broker:
        def holdings(self):
            return [
                {
                    "tradingsymbol": symbol,
                    "isin": "ISIN" + symbol,
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": units,
                    "instrument_token": token,
                    "average_price": 10,
                    "last_price": 25,
                }
                for symbol, units, token in [("ABC", 6, 1), ("NEW", 2, 2), ("IGNORED", 3, 3)]
            ]

        def positions(self):
            return {"net": []}

    class Accounts:
        def validate(self, account_id):
            pass

        def client(self, account_id):
            return Broker()

    sync = PortfolioSync(ledger.path, Accounts(), ledger, market)
    review = sync.preview_holdings("account")
    new_id = next(h["instrument_id"] for h in review["holdings"] if h["symbol"] == "NEW")
    assert sync.import_holdings("account")["imported_positions"] == 0
    result = sync.import_holdings("account", [new_id], {new_id: "2026-04-15"})
    assert result["imported_positions"] == 1
    assert Decimal(result["cash_deducted"]) == 20
    assert ledger.projection("account").cash.amount == 236
    new_lot = next(
        lot for lot in ledger.projection("account").open_lots if lot.instrument_id == new_id
    )
    assert new_lot.opened_on == date(2026, 4, 15)
    assert ledger.events("account")[: len(original_events)] == original_events
    assert ledger.journal("account") == original_journal
    assert ledger.projection("account").realised_pnl.amount == Decimal("17.2")
    assert next(
        h for h in sync.holding_snapshot("account")["holdings"] if h["instrument_id"] == new_id
    )["purchase_date_known"]
    assert sync.import_holdings("account")["imported_positions"] == 0
    assert sync.import_holdings("account", [new_id], {})["imported_positions"] == 0
    assert ledger.projection("account").cash.amount == 236
    assert all(
        market.instrument_by_id(lot.instrument_id)["symbol"] != "IGNORED"
        for lot in ledger.projection("account").open_lots
    )
    valuation_date = date.fromisoformat(max(e["occurred_at"][:10] for e in ledger.events("account")))
    for instrument_id in {lot.instrument_id for lot in ledger.projection("account").open_lots}:
        market.upsert_bars(
            instrument_id,
            [NormalizedBar(instrument_id, valuation_date, 25, 25, 25, 25, 10)],
            "test-price",
        )
    valuation = client.get(f"/api/portfolio/accounts/account/valuation?as_of_date={valuation_date}").json
    assert valuation["history_complete"] is False
    assert valuation["return_basis"] == "recorded_capital_and_cash_funded_purchases"
    expected = (Decimal(valuation["equity"]) / Decimal(valuation["initial_balance"])) ** (
        Decimal(365)
        / Decimal((valuation_date - date.fromisoformat(valuation["opening_date"])).days)
    ) - 1
    assert abs(Decimal(valuation["xirr"]) - expected) < Decimal("1e-9")
    assert abs(Decimal(valuation["annualized_return"]) - expected) < Decimal("1e-9")
    assert Decimal(valuation["realised_pnl"]) == Decimal("17.2")
    uncertain_events = json.loads(json.dumps(ledger.events("account")))
    for event in uncertain_events:
        if event["event_type"] == "OPENING_POSITION_IMPORTED":
            provenance = json.loads(event["event"]["broker_provenance"])
            provenance["purchase_date_known"] = False
            event["event"]["broker_provenance"] = json.dumps(provenance)
    with patch.object(ledger, "events", return_value=uncertain_events):
        uncertain = client.get(
            f"/api/portfolio/accounts/account/valuation?as_of_date={valuation_date}"
        ).json
    assert uncertain["xirr"] is None and uncertain["annualized_return"] is None


@pytest.mark.parametrize("purchase_date", ["bad", "2026-01-01", "2099-01-01"])
def test_invalid_kite_purchase_dates_do_not_modify_ledger(tmp_path, purchase_date):
    _client, ledger, market = fixture(tmp_path)

    class Broker:
        def holdings(self):
            return [
                {
                    "tradingsymbol": "NEW",
                    "isin": "ISINNEW",
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": 2,
                    "instrument_token": 1,
                    "average_price": 10,
                    "last_price": 25,
                }
            ]

        def positions(self):
            return {"net": []}

    class Accounts:
        def validate(self, account_id):
            pass

        def client(self, account_id):
            return Broker()

    sync = PortfolioSync(ledger.path, Accounts(), ledger, market)
    instrument_id = sync.preview_holdings("account")["holdings"][0]["instrument_id"]
    with pytest.raises(DomainValidationError, match="purchase dates"):
        sync.import_holdings("account", [instrument_id], {instrument_id: purchase_date})
    assert ledger.events("account") == []
