from datetime import date
from decimal import Decimal

import pytest

from src.domains.portfolio_accounting import Ledger
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.corporate_actions import CorporateActions
from src.gates.workflows.tradebook_import import TradebookImport
from src.platform_kernel import DomainValidationError, Money

HEADER = "symbol,isin,trade_date,trade_type,quantity,price,trade_id\n"


def setup(tmp_path):
    path = tmp_path / "actions.db"
    ledger, market = Ledger(path), MarketRepository(path)
    ledger.open_account("account", Money(10000), date(2026, 2, 1))
    return ledger, market, CorporateActions(path, market), TradebookImport(path, ledger, market)


def detect(service, symbol="ABC", day="2026-07-10", kind="SPLIT", ratio="1:5", isin="NEW"):
    service.detect_events(
        [{"symbol": symbol, "isin": isin, "ex_date": day, "action_type": kind, "ratio": ratio}]
    )


def apply(importer, preview):
    return importer.apply(
        "account",
        {
            "mode": "history",
            "upload_id": preview["upload_id"],
            "expected_version": preview["expected_version"],
            "selected_instrument_ids": [
                h["instrument_id"] for h in preview["holdings"] if h["eligible"]
            ],
        },
    )


def test_other_stock_split_uses_exchange_event_and_bridges_isin_in_full_history(tmp_path):
    ledger, market, service, importer = setup(tmp_path)
    market.upsert_instruments(
        [TrackedInstrument("abc", "NEW", "ABC", "NSE", "1", date(2026, 2, 1))]
    )
    detect(service)
    raw = (HEADER + "ABC,OLD,2026-03-01,buy,10,100,1\nABC,NEW,2026-08-01,sell,40,25,2\n").encode()
    review = importer.preview("account", raw, "history")
    assert len(review["holdings"]) == 1
    assert review["holdings"][0]["instrument_id"] == "abc"
    assert review["holdings"][0]["csv_units"] == 10
    assert Decimal(review["summary"]["realised_pnl"]) == 200
    assert ledger.events("account") == []  # preview never imports
    result = apply(importer, review)
    assert result["corporate_actions"] == 1
    assert ledger.projection("account").open_lots[0].unit_cost.amount == 20
    assert (
        ledger.projection_at("account", date(2026, 7, 9)).open_lots[0].remaining_units.units == 10
    )
    assert ledger.journal("account")[0]["buy_price"] == "20"
    assert apply(importer, importer.preview("account", raw, "history")) == result


def test_multiple_splits_chain_all_three_isins(tmp_path):
    ledger, _market, service, importer = setup(tmp_path)
    detect(service, day="2026-04-01", ratio="1:2", isin="MID")
    detect(service, day="2026-07-01", ratio="1:5", isin="NEW")
    raw = (
        HEADER
        + "ABC,OLD,2026-03-01,buy,10,100,1\nABC,MID,2026-05-01,buy,10,60,2\nABC,NEW,2026-08-01,sell,120,12,3\n"
    ).encode()
    review = importer.preview("account", raw, "history")
    assert len(review["holdings"]) == 1
    assert review["holdings"][0]["csv_units"] == 30
    assert Decimal(review["summary"]["realised_pnl"]) == 200
    assert apply(importer, review)["corporate_actions"] == 2
    assert sum(Decimal(t["realised_pnl"]) for t in ledger.journal("account")) == 200


def test_kmew_subdivision_resolves_actual_old_and_new_isins(tmp_path):
    ledger, _market, service, importer = setup(tmp_path)
    ledger.open_account("older", Money(300000), date(2025, 12, 1))
    detect(
        service,
        symbol="KMEW",
        day="2025-12-22",
        kind="Sub-Division from Rs. 10/- to Rs. 5/-",
        ratio="5:10",
        isin="INE0CJD01029",
    )
    raw = (
        HEADER
        + "KMEW,INE0CJD01011,2025-12-10,buy,2,3258.3,1\nKMEW,INE0CJD01029,2026-02-09,sell,4,1713.65,2\n"
    ).encode()
    review = importer.preview("older", raw, "history")
    assert review["unresolved_symbols"] == []
    assert review["closed_symbols"] == 1
    assert Decimal(review["summary"]["realised_pnl"]) == Decimal("338.00")
    assert ledger.events("older") == []


def test_buy_only_export_uses_current_exchange_isin_after_split(tmp_path):
    _ledger, _market, service, importer = setup(tmp_path)
    detect(service)
    raw = (HEADER + "ABC,OLD,2026-03-01,buy,10,100,1\n").encode()
    review = importer.preview("account", raw, "history")
    assert review["holdings"][0]["csv_units"] == 50
    assert apply(importer, review)["corporate_actions"] == 1


def test_bonus_preserves_original_fifo_cost_and_adds_zero_cost_lot(tmp_path):
    ledger, _market, service, importer = setup(tmp_path)
    detect(service, kind="BONUS", ratio="1:3", isin="NEW")
    raw = (HEADER + "ABC,NEW,2026-03-01,buy,6,100,1\nABC,NEW,2026-08-01,sell,7,90,2\n").encode()
    review = importer.preview("account", raw, "history")
    adjustment = review["corporate_action_adjustments"][0]
    assert adjustment["units_before"] == 6 and adjustment["units_after"] == 8
    assert "allotment" in adjustment["date_note"]
    assert Decimal(review["summary"]["realised_pnl"]) == 30
    assert review["holdings"][0]["lots"][0]["unit_cost"] == "0"
    apply(importer, review)
    assert ledger.projection("account").open_lots[0].unit_cost.amount == 0
    journal = ledger.journal("account")
    assert sum(Decimal(t["realised_pnl"]) for t in journal) == 30
    assert journal[0]["buy_date"] == "2026-03-01"
    assert journal[1]["buy_date"] == "2026-07-10"
    assert journal[1]["buy_price"] == "0"


@pytest.mark.parametrize(
    "kind,ratio", [("SPLIT", ""), ("RIGHTS", "1:2"), ("DEMERGER", "1:1"), ("BONUS", "1:3")]
)
def test_missing_ratios_complex_actions_and_fractional_entitlements_exclude_only_affected_stock(
    tmp_path, kind, ratio
):
    ledger, _market, service, importer = setup(tmp_path)
    detect(service, kind=kind, ratio=ratio)
    raw = (
        HEADER + "ABC,NEW,2026-03-01,buy,5,100,1\nGOOD,GOODISIN,2026-03-01,buy,2,10,2\n"
    ).encode()
    review = importer.preview("account", raw, "history")
    assert not next(h for h in review["holdings"] if h["symbol"] == "ABC")["eligible"]
    assert next(h for h in review["holdings"] if h["symbol"] == "GOOD")["eligible"]
    assert apply(importer, review)["imported_trades"] == 1
    assert ledger.projection("account").cash.amount == 9980


def test_mwl_uses_exchange_record_without_stock_specific_override(tmp_path):
    _ledger, _market, service, importer = setup(tmp_path)
    detect(service, symbol="MWL", ratio="1:10", isin="INE0JYY01029")
    raw = (
        HEADER
        + "MWL,INE0JYY01011,2026-03-01,buy,10,100,1\nMWL,INE0JYY01029,2026-08-01,sell,100,12,2\n"
    ).encode()
    review = importer.preview("account", raw, "history")
    assert len(review["corporate_action_adjustments"]) == 1
    assert Decimal(review["summary"]["realised_pnl"]) == 200


def test_mwl_without_exchange_event_is_unresolved_and_not_adjusted(tmp_path):
    _ledger, _market, _service, importer = setup(tmp_path)
    raw = (
        HEADER
        + "MWL,INE0JYY01011,2026-03-01,buy,10,100,1\nMWL,INE0JYY01029,2026-08-01,sell,100,12,2\n"
    ).encode()
    review = importer.preview("account", raw, "history")
    assert review["corporate_action_adjustments"] == []
    assert review["unresolved_symbols"]


def test_cached_exchange_notice_with_singular_currency_recovers_missing_ratio(tmp_path):
    _ledger, _market, service, importer = setup(tmp_path)
    service.detect_events(
        [
            {
                "symbol": "ANY",
                "isin": "OLD",
                "ex_date": "2026-07-10",
                "action_type": "SPLIT",
                "raw_json": '{"subject":"Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share"}',
            }
        ]
    )
    raw = (HEADER + "ANY,OLD,2026-03-01,buy,10,100,1\nANY,NEW,2026-08-01,sell,100,12,2\n").encode()
    review = importer.preview("account", raw, "history")
    assert review["unresolved_symbols"] == []
    assert review["corporate_action_adjustments"][0]["numerator"] == 10
    assert Decimal(review["summary"]["realised_pnl"]) == 200


def test_refresh_downloads_before_preview_and_reuses_covered_window(tmp_path, monkeypatch):
    _ledger, market, service, _importer = setup(tmp_path)
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def corporate_actions(self, **kwargs):
            calls.append(kwargs)
            return [
                {
                    "symbol": "ABC",
                    "isin": "NEW",
                    "exDate": "10-Jul-2026",
                    "subject": "Sub-Division from Rs. 10/- to Rs. 2/-",
                }
            ]

    monkeypatch.setattr("src.gates.workflows.tradebook_corporate_actions.NseClient", Client)
    importer = TradebookImport(service.database, _ledger, market, service)
    raw = (HEADER + "ABC,OLD,2026-03-01,buy,10,100,1\nABC,NEW,2026-08-01,sell,40,25,2\n").encode()
    first = importer.preview("account", raw, "history")
    assert first["holdings"][0]["eligible"]
    assert first["corporate_action_warnings"] == []
    importer.preview("account", raw, "history")
    assert len(calls) == 1


def test_failed_refresh_uses_cached_events_and_displays_warning(tmp_path):
    ledger, market, service, _importer = setup(tmp_path)
    detect(service)

    class FailedRefresh:
        def detect_job(self, payload, **kwargs):
            raise DomainValidationError("NSE failed")

    importer = TradebookImport(service.database, ledger, market, FailedRefresh())
    raw = (HEADER + "ABC,NEW,2026-03-01,buy,10,100,1\n").encode()
    review = importer.preview("account", raw, "history")
    assert review["holdings"][0]["csv_units"] == 50
    assert "cached" in review["corporate_action_warnings"][0]
    assert ledger.events("account") == []
