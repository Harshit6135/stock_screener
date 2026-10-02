"""Phase 5: Portfolio and Broker Account Integration tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.portfolio_sync import PortfolioSync
from src.application.strategy_definitions import StrategyDefinitions
from src.application.strategy_runtime import StrategyRuntime
from src.execution_gateway.kite_accounts import KiteAccounts
from src.execution_gateway.ledger import Ledger
from src.indicators.registry import PandasTaAdapter
from src.platform_kernel import Money, Quantity
from src.portfolio_accounting.api import Fill, FillSide, OpeningPosition, project


def test_kite_account_registration_and_linking(tmp_path):
    database = tmp_path / "system.db"
    accounts = KiteAccounts(database)
    
    accounts.register_account("broker1", "My Broker", "key1", "secret1")
    accs = accounts.list_accounts()
    assert len(accs) == 1
    assert accs[0]["broker_account_id"] == "broker1"
    assert accs[0]["account_name"] == "My Broker"
    assert "api_key" not in accs[0]

    # Link a strategy portfolio
    # Need to seed RETAINED_STRATEGIES (momentum) first
    definitions = StrategyDefinitions(database, PandasTaAdapter())
    runtime = StrategyRuntime(definitions)
    from pathlib import Path
    runtime.seed(Path(__file__).resolve().parents[1] / "strategies")
    
    accounts.link_portfolio("broker1", "momentum", "ledger_mom_1")
    ledger_id = accounts.get_portfolio("broker1", "momentum")
    assert ledger_id == "ledger_mom_1"

def test_opening_position_projection():
    cash = Money(Decimal(10000), "INR")
    op = OpeningPosition(
        "inst1",
        date(2026, 1, 1),
        Quantity(100),
        Money(Decimal(50), "INR"),
        datetime(2026, 9, 10, tzinfo=UTC),
        "broker_snapshot"
    )
    # Project just opening position
    proj = project(cash, [op])
    assert proj.cash.amount == Decimal(10000)  # Cash is unchanged by imported positions
    assert len(proj.open_lots) == 1
    assert proj.open_lots[0].remaining_units.units == 100
    assert proj.open_lots[0].unit_cost.amount == 50

    # Sell imported position
    sell = Fill(
        "inst1",
        date(2026, 9, 11),
        FillSide.SELL,
        Quantity(50),
        Money(Decimal(60), "INR"),
        executed_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    )
    proj2 = project(cash, [op, sell])
    assert proj2.cash.amount == Decimal(13000) # 10000 + 50 * 60
    assert proj2.realised_pnl.amount == Decimal(500) # (60-50)*50 = 500
    assert proj2.open_lots[0].remaining_units.units == 50

def test_ledger_import_opening_positions(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.open_account("acc1", Money(Decimal(10000), "INR"))
    
    op = OpeningPosition(
        "inst1",
        date(2026, 1, 1),
        Quantity(100),
        Money(Decimal(50), "INR"),
        datetime(2026, 9, 10, tzinfo=UTC),
        "broker_snapshot"
    )
    ledger.import_opening_positions("acc1", "idem_1", 0, [op])
    
    proj = ledger.projection("acc1")
    assert proj.cash.amount == Decimal(10000)
    assert len(proj.open_lots) == 1
    assert proj.open_lots[0].remaining_units.units == 100
    
    journal = ledger.journal("acc1")
    assert len(journal) == 0  # Imported positions only appear as buys once closed
    
    # Sell 50
    sell = Fill(
        "inst1",
        date(2026, 9, 11),
        FillSide.SELL,
        Quantity(50),
        Money(Decimal(60), "INR"),
        executed_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    )
    ledger.record_fills("acc1", "idem_2", 1, [sell])
    
    journal = ledger.journal("acc1")
    assert len(journal) == 1
    assert journal[0]["units"] == 50
    assert journal[0]["realised_pnl"] == "500"


def test_account_scoped_setup_and_reconciliation(tmp_path):
    database = tmp_path / "system.db"
    from src.application.market_repository import MarketRepository, TrackedInstrument
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
    market.upsert_instruments([TrackedInstrument("inst", "ISIN", "INST", "NSE", "1", date(2026, 1, 1))])
    sync = PortfolioSync(database, accounts, ledger, market)
    result = sync.setup({
        "broker_account_id": "broker", "strategy_id": "momentum", "opening_cash": "1000",
        "idempotency_key": "setup-1", "positions": [{
            "instrument_id": "inst", "units": 2, "unit_cost": "100",
            "acquisition_date": "2026-01-01", "provenance": "broker-holdings",
        }],
    })
    assert result["ledger_account_id"] == "managed-momentum"
    reconciled = sync.reconcile({
        "broker_account_id": "broker", "strategy_id": "momentum", "idempotency_key": "trade-1",
        "trades": [{"trade_id": "T1", "instrument_id": "inst", "side": "SELL", "units": 1,
                    "price": "120", "executed_at": "2027-02-01T09:15:00+00:00"}],
    })
    assert reconciled["posted_fills"] == 1
