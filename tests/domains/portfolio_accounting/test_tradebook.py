import pytest

from src.domains.portfolio_accounting.tradebook import canonical_symbol, parse_tradebook
from src.platform_kernel import DomainValidationError


@pytest.mark.parametrize(
    "symbol",
    [
        "ABC-EQ",
        "ABC-SM",
        "ABC-ST",
        "ABC-SZ",
        "ABC-A",
        "ABC-B",
        "ABC-XT",
        "ABC (BE)",
        "ABC – EQ",
        "ABC BE",
    ],
)
def test_equity_series_normalization(symbol):
    assert canonical_symbol(symbol) == "ABC"


@pytest.mark.parametrize(
    "symbol", ["MCDOWELL-N", "ABC-N1", "ABC-RE", "ABC-PART", "ABCDEF", "ABC-UNKNOWN"]
)
def test_normalization_preserves_security_names_and_distinct_classes(symbol):
    assert canonical_symbol(symbol) == symbol


def test_fifo_partial_sales_duplicate_executions_and_metadata_header():
    raw = b"""Zerodha equity tradebook
Symbol,Trade Date,Trade Type,Quantity,Price,Trade ID,Exchange
ABC,01/07/2026,buy,10,10,1,NSE
ABC,01/08/2026,buy,20,20,2,NSE
ABC,01/08/2026,buy,20,20,2,NSE
ABC,01/09/2026,sell,15,30,3,NSE
"""
    data = parse_tradebook(raw)
    assert data["duplicate_rows"] == 1
    assert data["open_groups"][0]["units"] == 15
    assert data["open_groups"][0]["lots"][0]["date"] == "2026-08-01"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not,a,tradebook",
        b"symbol,trade_date,trade_type,quantity,price\nABC,2026-01-01,buy,1,NaN",
        b"symbol,trade_date,trade_type,quantity,price\nABC,2026-01-01,sell,1,10",
        b"symbol,trade_date,trade_type,quantity,price\nABC,2026-01-01,buy,1.5,10",
    ],
)
def test_invalid_or_incomplete_tradebook_is_rejected(raw):
    with pytest.raises(DomainValidationError):
        parse_tradebook(raw)


def test_verified_split_bridges_isin_change_and_preserves_lot_cost():
    action = {
        "symbol": "ABC",
        "action_type": "SPLIT",
        "effective_date": "2026-07-10",
        "old_isin": "OLD",
        "new_isin": "NEW",
        "numerator": 10,
        "denominator": 1,
    }
    raw = b"""symbol,isin,trade_date,trade_type,quantity,price
ABC,OLD,2026-05-25,buy,60,370
ABC,NEW,2026-07-21,sell,260,36
ABC,NEW,2026-07-21,sell,340,36
"""
    result = parse_tradebook(raw, corporate_actions=[action])
    assert result["open_groups"] == []
    assert result["closed_symbols"] == 1
    assert result["corporate_action_adjustments"][0]["units_after"] == 600
    partial = raw.replace(b"sell,340", b"sell,300")
    lot = parse_tradebook(partial, corporate_actions=[action])["open_groups"][0]["lots"][0]
    assert lot == {"date": "2026-05-25", "units": 40, "unit_cost": "37", "trade_id": ""}
    before = parse_tradebook(
        raw.split(b"ABC,NEW")[0], corporate_actions=[action], as_of="2026-06-01"
    )
    assert before["open_groups"][0]["units"] == 60
    after = parse_tradebook(
        raw.split(b"ABC,NEW")[0], corporate_actions=[action], as_of="2026-07-10"
    )
    assert after["open_groups"][0]["units"] == 600
    assert after["open_groups"][0]["lots"][0]["unit_cost"] == "37"


def test_unresolved_unrelated_symbol_can_be_excluded_without_guessing_a_split():
    raw = b"""symbol,trade_date,trade_type,quantity,price
BAD,2026-01-01,sell,100,10
GOOD,2026-01-02,buy,5,20
"""
    result = parse_tradebook(raw, allow_unresolved=True)
    assert result["open_groups"][0]["symbol"] == "GOOD"
    assert result["unresolved_groups"][0]["symbol"] == "BAD"
    assert result["corporate_action_adjustments"] == []
