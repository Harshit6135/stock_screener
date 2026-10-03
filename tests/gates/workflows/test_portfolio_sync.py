from datetime import date

from src.domains.execution import KiteAccounts
from src.domains.indicators.registry import PandasTaAdapter
from src.domains.portfolio_accounting import Ledger
from src.gates.strategy_definitions import StrategyDefinitions
from src.gates.strategy_runtime import StrategyRuntime
from src.gates.workflows.portfolio_sync import PortfolioSync


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
