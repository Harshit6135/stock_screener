from datetime import date

from src.domains.execution import KiteAccounts
from src.domains.indicators.registry import PandasTaAdapter
from src.domains.portfolio_accounting import Ledger
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.portfolio_sync import PortfolioSync


def test_delivery_import_includes_today_and_refreshes_without_duplicates(tmp_path):
    import pytest
    from flask import Flask

    from src.gates.http.portfolio import create_portfolio_blueprint
    from src.gates.repositories import MarketRepository, TrackedInstrument
    from src.platform_kernel import DomainValidationError, Money

    class Broker:
        holding_units = 5

        def __init__(self, api_key):
            assert api_key == "key"

        def set_access_token(self, token):
            assert token == "token"

        def profile(self):
            return {"user_id": "owner"}

        def holdings(self):
            return [
                {"isin": "OLD", "tradingsymbol": "OLD", "exchange": "BSE", "product": "CNC", "instrument_token": 101,
                 "quantity": self.holding_units, "t1_quantity": 2, "average_price": 10, "last_price": 14},
                {"isin": "ETF", "tradingsymbol": "ETF", "exchange": "NSE", "product": "CNC", "instrument_token": 3,
                 "quantity": 4, "average_price": 20, "last_price": 22},
            ]

        def positions(self):
            return {"net": [
                {"tradingsymbol": "NEW", "exchange": "NSE", "product": "CNC", "instrument_token": 2,
                 "quantity": 3, "average_price": 30, "last_price": 35},
                {"tradingsymbol": "OLD", "exchange": "NSE", "product": "CNC", "instrument_token": 1,
                 "quantity": 1, "average_price": 18, "last_price": 15},
                {"tradingsymbol": "MIS", "exchange": "NSE", "product": "MIS", "instrument_token": 99,
                 "quantity": 5, "average_price": 30, "last_price": 35},
            ]}

    database = tmp_path / "system.db"
    accounts = KiteAccounts(database, client_factory=Broker)
    accounts.register_account("owner", "Owner", "key", "secret")
    accounts.update_session("owner", "token", "owner")
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("owner", Money("1000"))
    market.upsert_instruments([TrackedInstrument("old", "OLD", "OLD", "NSE", "1", date(2026, 1, 1)),
                               TrackedInstrument("new", "NEW", "NEW", "NSE", "2", date(2026, 1, 1))])
    sync = PortfolioSync(database, accounts, ledger, market)
    preview = sync.preview_holdings("owner")
    assert ledger.events("owner") == []
    assert len(market.tracked_instruments()) == 2
    with pytest.raises(DomainValidationError, match="select holdings"):
        sync.import_holdings("owner")
    result = sync.import_holdings("owner", [row["instrument_id"] for row in preview["holdings"]])
    assert result["imported_positions"] == 3
    lots = {lot.instrument_id: lot for lot in ledger.projection("owner").open_lots}
    assert lots["old"].remaining_units.units == 8
    assert str(lots["old"].unit_cost.amount) == "11"
    assert lots["new"].remaining_units.units == 3
    assert ledger.projection("owner").cash.amount == 742
    assert sync.import_holdings("owner")["imported_positions"] == 0
    assert ledger.accounts()[0]["version"] == 4
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market, broker_sync=sync))
    snapshot = sync.holding_snapshot("owner")
    valuation = app.test_client().get(f"/api/portfolio/accounts/owner/valuation?as_of_date={snapshot['observed_at'][:10]}")
    assert valuation.status_code == 200
    assert valuation.json["market_value"] == "313"
    assert all(row["price_basis"] == "kite-portfolio-snapshot" for row in valuation.json["holdings"])
    assert next(row for row in valuation.json["holdings"] if row["symbol"] == "OLD")["purchase_date_known"] is False
    Broker.holding_units = 6
    with pytest.raises(DomainValidationError, match="quantities differ"):
        sync.import_holdings("owner")
    assert ledger.accounts()[0]["version"] == 4


def test_kite_account_registration_and_linking(tmp_path):
    database = tmp_path / "system.db"
    accounts = KiteAccounts(database)
    accounts.register_account("broker1", "My Broker", "key1", "secret1")
    accs = accounts.list_accounts()
    assert len(accs) == 1
    assert accs[0]["broker_account_id"] == "broker1"
    assert accs[0]["account_name"] == "My Broker"
    assert "api_key" not in accs[0]
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    from pathlib import Path

    runtime.seed(Path(__file__).resolve().parents[2] / "strategies")
    accounts.link_portfolio("broker1", "momentum", "ledger_mom_1")
    ledger_id = accounts.get_portfolio("broker1", "momentum")
    assert ledger_id == "ledger_mom_1"


def test_selected_import_remembers_ignored_holdings_and_can_add_later(tmp_path):
    import pytest

    from src.gates.repositories import MarketRepository, TrackedInstrument
    from src.platform_kernel import DomainValidationError, Money

    class Broker:
        def __init__(self, api_key):
            pass

        def set_access_token(self, token):
            pass

        def profile(self):
            return {"user_id": "owner"}

        def holdings(self):
            return [{"isin": key, "tradingsymbol": key, "exchange": "NSE", "product": "CNC",
                     "instrument_token": index, "quantity": 2, "average_price": 10, "last_price": 15}
                    for index, key in enumerate(["A", "B"], 1)]

        def positions(self):
            return {"net": []}

    database = tmp_path / "selected.db"
    accounts = KiteAccounts(database, client_factory=Broker)
    accounts.register_account("owner", "Owner", "key", "secret")
    accounts.update_session("owner", "token", "owner")
    market, ledger = MarketRepository(database), Ledger(database)
    market.upsert_instruments([TrackedInstrument(key, key, key, "NSE", str(index), date(2026, 1, 1))
                               for index, key in enumerate(["A", "B"], 1)])
    ledger.open_account("owner", Money("100"))
    sync = PortfolioSync(database, accounts, ledger, market)
    assert sync.import_holdings("owner", ["A"])["ignored_count"] == 1
    assert sync.import_holdings("owner")["holding_count"] == 1
    assert [lot.instrument_id for lot in ledger.projection("owner").open_lots] == ["A"]
    assert sync.holding_snapshot("owner")["ignored_instrument_ids"] == ["B"]
    assert ledger.accounts()[0]["version"] == 2
    assert ledger.projection("owner").cash.amount == 80
    with pytest.raises(DomainValidationError, match="cannot be removed"):
        sync.import_holdings("owner", ["B"])
    with pytest.raises(DomainValidationError, match="no longer exists"):
        sync.import_holdings("owner", ["A", "unknown"])
    result = sync.import_holdings("owner", ["A", "B"])
    assert result["imported_positions"] == 1
    assert result["ignored_count"] == 0
    assert ledger.accounts()[0]["version"] == 4
    assert ledger.projection("owner").cash.amount == 60
    assert sync.import_holdings("owner")["imported_positions"] == 0


def test_account_scoped_setup_and_reconciliation(tmp_path):
    database = tmp_path / "system.db"
    from src.gates.repositories import MarketRepository, TrackedInstrument

    class FakeBroker:
        def __init__(self, api_key):
            assert api_key == "key"

        def set_access_token(self, token):
            assert token == "fixture-token"

        def profile(self):
            return {"user_id": "fixture-user"}

        def holdings(self):
            return [{"isin": "ISIN", "quantity": 2}]

    accounts = KiteAccounts(database, client_factory=FakeBroker)
    accounts.register_account("broker", "Broker", "key", "secret")
    accounts.update_session("broker", "fixture-token", "fixture-user")
    accounts.link_portfolio("broker", "momentum", "managed-momentum")
    ledger = Ledger(database)
    market = MarketRepository(database)
    market.upsert_instruments(
        [TrackedInstrument("inst", "ISIN", "INST", "NSE", "1", date(2026, 1, 1))]
    )
    sync = PortfolioSync(database, accounts, ledger, market)
    result = sync.setup(
        {
            "broker_account_id": "broker",
            "strategy_id": "momentum",
            "opening_cash": "1000",
            "idempotency_key": "setup-1",
            "positions": [
                {
                    "instrument_id": "inst",
                    "units": 2,
                    "unit_cost": "100",
                    "acquisition_date": "2026-01-01",
                    "provenance": "broker-holdings",
                }
            ],
        }
    )
    assert result["ledger_account_id"] == "managed-momentum"
    reconciled = sync.reconcile(
        {
            "broker_account_id": "broker",
            "strategy_id": "momentum",
            "idempotency_key": "trade-1",
            "trades": [
                {
                    "trade_id": "T1",
                    "instrument_id": "inst",
                    "side": "SELL",
                    "units": 1,
                    "price": "120",
                    "executed_at": "2027-02-01T09:15:00+00:00",
                }
            ],
        }
    )
    assert reconciled["posted_fills"] == 1
