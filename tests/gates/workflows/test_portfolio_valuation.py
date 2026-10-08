from datetime import date

from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.gates.repositories import MarketRepository, NormalizedBar, TrackedInstrument
from src.gates.workflows.portfolio_valuation import portfolio_valuation
from src.platform_kernel import Money, Quantity


def test_valuation_reuses_instrument_reads_across_lots(tmp_path, monkeypatch):
    database = tmp_path / "valuation.db"
    ledger, market = Ledger(database), MarketRepository(database)
    day = date(2026, 2, 2)
    ledger.open_account("account", Money(1000), date(2026, 2, 1))
    market.upsert_instruments([TrackedInstrument("abc", "ABC", "ABC", "NSE", "1", day)])
    ledger.record_fills(
        "account",
        "buys",
        0,
        [
            Fill("abc", day, FillSide.BUY, Quantity(1), Money(100)),
            Fill("abc", day, FillSide.BUY, Quantity(2), Money(110)),
        ],
    )
    market.upsert_bars("abc", [NormalizedBar("abc", day, 120, 120, 120, 120, 1)], "prices")
    bars, identity = market.bars, market.instrument_by_id
    bar_reads, identity_reads = [], []

    def counted_bars(*args, **kwargs):
        bar_reads.append(args[0])
        return bars(*args, **kwargs)

    def counted_identity(instrument_id):
        identity_reads.append(instrument_id)
        return identity(instrument_id)

    monkeypatch.setattr(market, "bars", counted_bars)
    monkeypatch.setattr(market, "instrument_by_id", counted_identity)
    before = ledger.events("account")
    result = portfolio_valuation(ledger, market, "account", day)
    assert result["equity"] == "1040"
    assert result["holdings"][0]["units"] == 3
    assert result["holdings"][0]["cost"] == "320"
    assert identity_reads == ["abc"]
    assert bar_reads == ["abc", "abc"]  # one price read and one stop-history read.
    assert ledger.events("account") == before
    assert not ledger.valuations("account")
