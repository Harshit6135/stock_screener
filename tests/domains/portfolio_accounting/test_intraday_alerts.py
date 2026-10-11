from datetime import UTC, datetime
from types import SimpleNamespace

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.portfolio_accounting import Fill, FillSide, IntradayStopAlerts, Ledger
from src.platform_kernel import ArtifactStore, Money, Quantity


def test_intraday_stop_alert_is_immutable_and_does_not_create_fill(tmp_path):
    database = tmp_path / "system.db"
    ledger = Ledger(database)
    ledger.open_account("paper", Money(1000))
    ledger.record_fills(
        "paper",
        "buy-1",
        0,
        [
            Fill(
                "ABC",
                datetime(2026, 9, 1, tzinfo=UTC).date(),
                FillSide.BUY,
                Quantity(1),
                Money(100),
                Money(0),
                datetime(2026, 9, 1, 9, 15, tzinfo=UTC),
            )
        ],
    )
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    risk = SimpleNamespace(
        risk_projection=lambda account: [
            {
                "account_id": account,
                "action_date": "2026-09-04",
                "stop_model": "ATR",
                "positions": [{"instrument_id": "ABC", "current_trailing_stop": "95"}],
            }
        ]
    )
    alerts = IntradayStopAlerts(database, ledger, risk, publisher)
    payload = {
        "account_id": "paper",
        "observations": [
            {"instrument_id": "ABC", "price": "89", "observed_at": "2026-09-10T10:00:00+00:00"}
        ],
    }
    first = alerts.ingest(payload)
    second = alerts.ingest(payload)
    assert first["alert_count"] == second["alert_count"] == 1
    assert first["fills_created"] == 0
    assert len(ledger.events("paper")) == 1
    assert alerts.read("paper")[0]["alert_id"] == first["alerts"][0]["alert_id"]
    payload["observations"][0]["price"] = "94"
    assert alerts.ingest(payload)["alert_count"] == 0  # Below normal stop, above hard stop.
