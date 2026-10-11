from datetime import UTC, date, datetime
from decimal import Decimal

from src.domains.portfolio_accounting import Fill, FillSide
from src.domains.portfolio_accounting.api import OpeningPosition, project
from src.platform_kernel import Money, Quantity


def test_opening_position_projection():
    cash = Money(Decimal(10000), "INR")
    op = OpeningPosition(
        "inst1",
        date(2026, 1, 1),
        Quantity(100),
        Money(Decimal(50), "INR"),
        datetime(2026, 9, 10, tzinfo=UTC),
        "broker_snapshot",
    )
    proj = project(cash, [op])
    assert proj.cash.amount == Decimal(10000)
    assert len(proj.open_lots) == 1
    assert proj.open_lots[0].remaining_units.units == 100
    assert proj.open_lots[0].unit_cost.amount == 50
    sell = Fill(
        "inst1",
        date(2026, 9, 11),
        FillSide.SELL,
        Quantity(50),
        Money(Decimal(60), "INR"),
        executed_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
    )
    proj2 = project(cash, [op, sell])
    assert proj2.cash.amount == Decimal(13000)
    assert proj2.realised_pnl.amount == Decimal(500)
    assert proj2.open_lots[0].remaining_units.units == 50


def test_fifo_projection_tracks_cash_open_lots_and_realised_pnl():
    fills = (
        Fill("ABC", date(2026, 1, 1), FillSide.BUY, Quantity(2), Money("100")),
        Fill("ABC", date(2026, 1, 2), FillSide.BUY, Quantity(1), Money("120")),
        Fill("ABC", date(2026, 1, 3), FillSide.SELL, Quantity(2), Money("130")),
    )
    projection = project(Money("500"), fills)
    assert projection.cash == Money("440")
    assert projection.realised_pnl == Money("60")
    assert projection.open_lots[0].remaining_units == Quantity(1)
