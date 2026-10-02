import pytest
from decimal import Decimal
from datetime import date, datetime, UTC

from src.execution_gateway.risk_guard import (
    RiskGuardLimits,
    PortfolioRiskConfig,
)
from src.application.managed_risk import ManagedRiskGuard
from src.execution_gateway.ledger import Ledger
from src.application.market_repository import MarketRepository
from src.platform_kernel import DomainValidationError, Money


def _setup_guard(tmp_path, limits=None, opening_cash=100000):
    """Common setup: database with ledger, market (creates all universe tables), and guard."""
    db = str(tmp_path / "system.db")
    ledger = Ledger(db)
    ledger.open_account("acc1", Money(Decimal(opening_cash)))
    # MarketRepository.__init__ creates universe_snapshot_members and
    # reference_instruments tables required by _sector().
    market = MarketRepository(db)
    config = PortfolioRiskConfig(db)
    if limits:
        config.update_limits(limits)

    class FakeMarket:
        """Wraps real MarketRepository but stubs bars() for instruments without data."""
        def __init__(self, real):
            self._real = real
        def bars(self, instrument_id, **kwargs):
            return [{"close": "100"}]
        def instrument_by_id(self, instrument_id):
            return self._real.instrument_by_id(instrument_id)

    guard = ManagedRiskGuard(db, ledger, FakeMarket(market), config, None)
    return db, ledger, config, guard


def test_portfolio_risk_config(tmp_path):
    db_path = tmp_path / "system.db"
    config = PortfolioRiskConfig(db_path)

    version, limits = config.get_limits()
    assert version == 1
    assert limits.max_positions is None

    new_version = config.update_limits(RiskGuardLimits(max_positions=5, max_concentration=0.2))
    assert new_version == 2

    version, limits = config.get_limits()
    assert version == 2
    assert limits.max_positions == 5
    assert limits.max_concentration == 0.2


def test_managed_risk_guard_max_positions(tmp_path):
    """ManagedRiskGuard enforces max_positions using real ledger state."""
    db, ledger, config, guard = _setup_guard(tmp_path, RiskGuardLimits(max_positions=1))

    # First BUY fits within max_positions=1.
    guard.validate("acc1", [{"instrument_id": "i1", "side": "BUY", "units": 1, "execution_price": "100"}])

    # Record a fill so the position is held.
    from src.portfolio_accounting import Fill, FillSide
    from src.platform_kernel import Quantity
    ledger.record_fills("acc1", "k1", 0, [
        Fill("i1", date(2026, 1, 1), FillSide.BUY, Quantity(1), Money(Decimal(100)),
             executed_at=datetime(2026, 1, 1, tzinfo=UTC)),
    ])

    # Second BUY for a different instrument should fail.
    with pytest.raises(DomainValidationError, match="maximum positions exceeded"):
        guard.validate("acc1", [{"instrument_id": "i2", "side": "BUY", "units": 1, "execution_price": "100"}])


def test_managed_risk_guard_max_order_value(tmp_path):
    """ManagedRiskGuard enforces max_order_value."""
    _, _, _, guard = _setup_guard(tmp_path, RiskGuardLimits(max_order_value=5000))

    with pytest.raises(DomainValidationError, match="maximum order value exceeded"):
        guard.validate("acc1", [{"instrument_id": "i1", "side": "BUY", "units": 100, "execution_price": "100"}])


def test_managed_risk_guard_min_reserve_cash(tmp_path):
    """ManagedRiskGuard enforces min_reserve_cash."""
    _, _, _, guard = _setup_guard(tmp_path, RiskGuardLimits(min_reserve_cash=500), opening_cash=1000)

    with pytest.raises(DomainValidationError, match="insufficient unreserved cash"):
        guard.validate("acc1", [{"instrument_id": "i1", "side": "BUY", "units": 8, "execution_price": "100"}])


def test_managed_risk_guard_writes_valuation_snapshot(tmp_path):
    """Validate writes a daily valuation snapshot for drawdown/loss guards."""
    _, ledger, _, guard = _setup_guard(tmp_path)

    guard.validate("acc1", [])

    snapshots = ledger.valuations("acc1")
    assert len(snapshots) >= 1
    assert "equity" in snapshots[0]["payload"]
