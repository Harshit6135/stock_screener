from datetime import date

from src.platform_kernel import Money, Quantity
from src.portfolio_accounting import Fill, FillSide, project


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
