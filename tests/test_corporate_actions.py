from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.application.catalog import ArtifactCatalog
from src.application.corporate_actions import CorporateActions
from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.publication import ArtifactPublisher
from src.execution_gateway import Ledger
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactStore, Money, Quantity
from src.portfolio_accounting import Fill, FillSide


def test_split_creates_adjusted_readback_without_changing_raw_bars(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments([TrackedInstrument(instrument_id, "INE000000001", "ABC", "NSE", "1", date(2026, 1, 1))])
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    market.upsert_bars(instrument_id, [NormalizedBar(instrument_id, date(2026, 1, 1), Decimal(100), Decimal(110), Decimal(90), Decimal(100), 10)], "raw-1")
    actions = CorporateActions(database, market, publisher)
    actions.record({"instrument_id": instrument_id, "effective_date": "2026-01-02", "action_type": "SPLIT", "ratio": "2", "amount": "0"})
    adjusted = actions.adjusted_bars(instrument_id, date(2026, 1, 1), date(2026, 1, 1))
    assert Decimal(adjusted["bars"][0]["close"]) == Decimal(50)
    assert market.bars(instrument_id, date(2026, 1, 1), date(2026, 1, 1))[0]["close"] == "100"


def test_delisting_exposes_explicit_liquidation_policy(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments([TrackedInstrument(instrument_id, "INE000000002", "XYZ", "NSE", "2", date(2026, 1, 1))])
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    market.upsert_bars(instrument_id, [NormalizedBar(instrument_id, date(2026, 1, 5), Decimal(100), Decimal(110), Decimal(90), Decimal(105), 10)], "raw-2")
    actions = CorporateActions(database, market, publisher)
    actions.record({"instrument_id": instrument_id, "effective_date": "2026-01-06", "action_type": "DELISTING", "ratio": "1", "amount": "0"})
    result = actions.adjusted_bars(instrument_id, date(2026, 1, 5), date(2026, 1, 6))
    assert result["liquidation_required"] is True
    assert result["delisting"]["liquidation_policy"] == "LIQUIDATE_AT_LAST_AVAILABLE_CLOSE"


def test_bonus_creates_distinct_adjusted_price_basis(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments([TrackedInstrument(instrument_id, "INE000000003", "BON", "NSE", "3", date(2026, 1, 1))])
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    market.upsert_bars(instrument_id, [NormalizedBar(instrument_id, date(2026, 1, 1), Decimal(100), Decimal(110), Decimal(90), Decimal(100), 10)], "raw-3")
    actions = CorporateActions(database, market, publisher)
    actions.record({"instrument_id": instrument_id, "effective_date": "2026-01-02", "action_type": "BONUS", "ratio": "1", "amount": "0"})
    adjusted = actions.adjusted_bars(instrument_id, date(2026, 1, 1), date(2026, 1, 1))
    assert Decimal(adjusted["bars"][0]["close"]) == Decimal(50)


def test_delisting_liquidation_plan_is_review_only(tmp_path):
    database = tmp_path / "system.db"
    market = MarketRepository(database)
    instrument_id = str(uuid4())
    market.upsert_instruments([TrackedInstrument(instrument_id, "INE000000004", "LIQ", "NSE", "4", date(2026, 1, 1))])
    market.upsert_bars(instrument_id, [NormalizedBar(instrument_id, date(2026, 1, 5), 100, 110, 90, 105, 10)], "raw-4")
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    ledger.record_fills("paper", "buy-1", 0, [Fill(instrument_id, date(2026, 1, 5), FillSide.BUY, Quantity(2), Money(100), Money(0))])
    actions = CorporateActions(database, market, publisher, ledger)
    actions.record({"instrument_id": instrument_id, "effective_date": "2026-01-06", "action_type": "DELISTING", "ratio": "1", "amount": "0"})
    plan = actions.liquidation_plan("paper", date(2026, 1, 7))
    assert plan["entries"][0]["price"] == "105"
    assert plan["fills_created"] == 0
    assert plan["requires_operator_review"] is True
