from datetime import date, timedelta
from decimal import Decimal

from src.domains.portfolio_accounting.api import Lot
from src.gates.workflows.portfolio_stops import portfolio_stops
from src.platform_kernel import Money, Quantity


class Market:
    def __init__(self, closes):
        self.rows = [
            {
                "as_of_date": (date(2026, 2, 1) + timedelta(days=i)).isoformat(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 100,
            }
            for i, close in enumerate(closes)
        ]

    def bars(self, instrument_id, start, end, limit):
        return [
            row for row in self.rows if start.isoformat() <= row["as_of_date"] <= end.isoformat()
        ][-limit:]


def lot(units=1, cost=100):
    return Lot("abc", date(2026, 2, 20), Quantity(units), Money(cost))


def test_entry_stop_and_ratchet_never_fall_with_price():
    market = Market([100] * 19 + [110] * 10 + [95] * 10)
    peak = portfolio_stops(market, [lot()], date(2026, 3, 1))["abc"]
    later = portfolio_stops(market, [lot()], date(2026, 3, 11))["abc"]
    assert peak["entry_stop"] == Decimal(96)
    assert later["current_trailing_stop"] == peak["current_trailing_stop"]
    assert later["risk_date"] == "2026-03-11"
    assert later["atr"] > 0


def test_existing_stop_takes_priority_and_future_bars_are_excluded():
    market = Market([100] * 29 + [200])
    saved = {"abc": {"stop": Decimal(120), "date": "2026-02-25"}}
    row = portfolio_stops(market, [lot()], date(2026, 3, 1), saved)["abc"]
    assert row["current_trailing_stop"] == 120
    assert row["risk_date"] == "2026-03-01"
    assert row["risk_basis"] == "persisted_atr_plus_completed_close_ratchet"


def test_insufficient_history_is_explicit_and_preserves_saved_stop():
    market = Market([100] * 13)
    assert (
        portfolio_stops(market, [lot()], date(2026, 3, 1))["abc"]["current_trailing_stop"] is None
    )
    row = portfolio_stops(
        market,
        [lot()],
        date(2026, 3, 1),
        {
            "abc": {"stop": Decimal(90), "date": "2026-02-10"},
        },
    )["abc"]
    assert row["current_trailing_stop"] == 90
    assert "14 completed" in row["risk_note"]


def test_same_day_fills_use_weighted_entry_cost():
    row = portfolio_stops(Market([100] * 30), [lot(1, 100), lot(3, 104)], date(2026, 3, 1))["abc"]
    assert row["entry_stop"] == Decimal(99)


def test_intraday_bar_is_excluded(monkeypatch):
    from datetime import datetime

    from src.gates.workflows import portfolio_stops as module

    class Clock:
        @staticmethod
        def now(zone):
            return datetime(2026, 3, 2, 12, tzinfo=zone)

    monkeypatch.setattr(module, "datetime", Clock)
    row = module.portfolio_stops(Market([100] * 29 + [200]), [lot()], date(2026, 3, 2))["abc"]
    assert row["risk_date"] == "2026-03-01"
    assert row["current_trailing_stop"] == Decimal(96)


def test_valuation_exposes_breached_stop_without_changing_ledger(tmp_path):
    from flask import Flask

    from src.domains.portfolio_accounting import Fill, FillSide, Ledger
    from src.gates.http.portfolio import create_portfolio_blueprint
    from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument

    database = tmp_path / "stops.db"
    ledger, market = Ledger(database), MarketRepository(database)
    ledger.open_account("account", Money(1000), date(2026, 2, 1))
    market.upsert_instruments(
        [TrackedInstrument("abc", "ABC", "ABC", "NSE", "1", date(2026, 2, 1))]
    )
    ledger.record_fills(
        "account", "buy", 0, [Fill("abc", date(2026, 2, 20), FillSide.BUY, Quantity(1), Money(100))]
    )
    market.upsert_bars(
        "abc",
        [
            NormalizedBar(
                "abc",
                date.fromisoformat(row["as_of_date"]),
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
            )
            for row in Market([100] * 19 + [110] * 10 + [95] * 10).rows
        ],
        "prices",
    )
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    before = ledger.events("account")
    result = (
        app.test_client()
        .get("/api/portfolio/accounts/account/valuation?as_of_date=2026-03-11")
        .json
    )
    holding = result["holdings"][0]
    assert Decimal(holding["current_trailing_stop"]) > 95
    assert Decimal(holding["hard_stop"]) == Decimal(holding["current_trailing_stop"]) * Decimal(
        "0.97"
    )
    assert holding["stop_status"] == "below_hard_stop"
    assert result["breached_stop_holdings"] == 1
    assert Decimal(result["stop_based_risk"]) == 0
    assert ledger.events("account") == before
