from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domains.portfolio_accounting import Ledger
from src.domains.portfolio_engine import PortfolioRiskConfig, RiskGuardLimits
from src.gates.repositories import MarketRepository
from src.gates.workflows.managed_risk import ManagedRiskGuard
from src.platform_kernel import DomainValidationError, Money, Quantity


def _setup_guard(tmp_path, limits=None, opening_cash=100000):
    """Build the persisted ledger, market repository, and managed guard."""
    db = str(tmp_path / "system.db")
    ledger = Ledger(db)
    ledger.open_account("acc1", Money(Decimal(opening_cash)))
    market = MarketRepository(db)
    config = PortfolioRiskConfig(db)
    if limits:
        config.update_limits(limits)

    class FakeMarket:
        def __init__(self, real):
            self._real = real

        def bars(self, instrument_id, **kwargs):
            return [{"close": "100"}]

        def instrument_by_id(self, instrument_id):
            return self._real.instrument_by_id(instrument_id)

    guard = ManagedRiskGuard(db, ledger, FakeMarket(market), config, None)
    return ledger, guard


def test_managed_risk_guard_max_positions(tmp_path):
    ledger, guard = _setup_guard(tmp_path, RiskGuardLimits(max_positions=1))
    guard.validate(
        "acc1", [{"instrument_id": "i1", "side": "BUY", "units": 1, "execution_price": "100"}]
    )
    from src.domains.portfolio_accounting import Fill, FillSide

    ledger.record_fills(
        "acc1",
        "k1",
        0,
        [
            Fill(
                "i1",
                date(2026, 1, 1),
                FillSide.BUY,
                Quantity(1),
                Money(Decimal(100)),
                executed_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
    )
    with pytest.raises(DomainValidationError, match="maximum positions exceeded"):
        guard.validate(
            "acc1", [{"instrument_id": "i2", "side": "BUY", "units": 1, "execution_price": "100"}]
        )


def test_managed_risk_guard_max_order_value(tmp_path):
    _, guard = _setup_guard(tmp_path, RiskGuardLimits(max_order_value=5000))
    with pytest.raises(DomainValidationError, match="maximum order value exceeded"):
        guard.validate(
            "acc1", [{"instrument_id": "i1", "side": "BUY", "units": 100, "execution_price": "100"}]
        )


def test_managed_risk_guard_min_reserve_cash(tmp_path):
    _, guard = _setup_guard(tmp_path, RiskGuardLimits(min_reserve_cash=500), opening_cash=1000)
    with pytest.raises(DomainValidationError, match="insufficient unreserved cash"):
        guard.validate(
            "acc1", [{"instrument_id": "i1", "side": "BUY", "units": 8, "execution_price": "100"}]
        )


def test_managed_risk_guard_writes_valuation_snapshot(tmp_path):
    ledger, guard = _setup_guard(tmp_path)
    guard.validate("acc1", [])
    snapshots = ledger.valuations("acc1")
    assert len(snapshots) >= 1
    assert "equity" in snapshots[0]["payload"]
