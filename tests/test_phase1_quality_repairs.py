from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.application.market_repository import MarketRepository, TrackedInstrument
from src.market_data import NormalizedBar
from src.platform_kernel import DomainValidationError

START = date(2026, 1, 5)


def repository(tmp_path, *, index=False):
    market = MarketRepository(tmp_path / "system.db")
    market.upsert_instruments([TrackedInstrument("stock", "INDEX:NIFTY500" if index else "IN0000000001",
                                                 "NIFTY 500" if index else "STOCK", "NSE", "42", START)])
    return market


def bar(offset, close=100, volume=100):
    price = Decimal(str(close))
    return NormalizedBar("stock", START+timedelta(days=offset), price, price, price, price, volume)


def test_sparse_repeat_does_not_invent_close_gap(tmp_path):
    market = repository(tmp_path)
    rows = [bar(0, 100), bar(1, 110), bar(2, 121)]
    market.upsert_bars("stock", rows, "initial")
    revision = market.market_history_revision("stock")
    market.upsert_bars("stock", [rows[0], rows[2]], "sparse-repeat")
    assert market.quality_events(check_type="close_gap") == []
    assert market.market_history_revision("stock") == revision


def test_sparse_repeat_respects_intervening_nonzero_volume(tmp_path):
    market = repository(tmp_path)
    rows = [bar(i, volume=100 if i == 3 else 0) for i in range(7)]
    market.upsert_bars("stock", rows, "initial")
    market.upsert_bars("stock", [item for i, item in enumerate(rows) if i != 3], "sparse-repeat")
    assert market.quality_events(check_type="zero_volume_streak") == []


def test_historical_correction_checks_stored_successor_and_retains_bars(tmp_path):
    market = repository(tmp_path)
    market.upsert_bars("stock", [bar(0), bar(1)], "initial")
    market.upsert_bars("stock", [bar(0, 50)], "correction")
    events = market.quality_events(check_type="close_gap")
    assert len(events) == 1
    assert events[0]["as_of_date"] == (START+timedelta(days=1)).isoformat()
    assert events[0]["detail"]["expected_close"] == 50
    assert events[0]["detail"]["source_snapshot_id"] == "initial"
    assert events[0]["detail"]["validation_snapshot_id"] == "correction"
    assert len(market.bars("stock", START, START+timedelta(days=1))) == 2
    market.upsert_bars("stock", [bar(0, 50)], "repeat")
    assert len(market.quality_events(check_type="close_gap")) == 1


def test_historical_volume_correction_checks_following_sessions(tmp_path):
    market = repository(tmp_path)
    market.upsert_bars("stock", [bar(i, volume=100 if i == 0 else 0) for i in range(6)], "initial")
    assert market.quality_events(check_type="zero_volume_streak") == []
    market.upsert_bars("stock", [bar(0, volume=0)], "correction")
    events = market.quality_events(check_type="zero_volume_streak")
    assert len(events) == 1
    assert events[0]["as_of_date"] == (START+timedelta(days=5)).isoformat()


def test_index_has_no_traded_volume_streak_warning(tmp_path):
    market = repository(tmp_path, index=True)
    market.upsert_bars("stock", [bar(i, volume=0) for i in range(10)], "index-history")
    assert market.quality_events(check_type="zero_volume_streak") == []


@pytest.mark.parametrize("filters", [{"limit": True}, {"limit": "10"}, {"offset": False},
                                     {"offset": "0"}, {"instrument_id": []}, {"check_type": " "}])
def test_invalid_quality_filters_fail_cleanly(tmp_path, filters):
    with pytest.raises(DomainValidationError, match="filters"):
        repository(tmp_path).quality_events(**filters)


@pytest.mark.parametrize("text", [
    "access_token=DO_NOT_PERSIST invalid session",
    'provider failed: {"api_secret": "DO_NOT_PERSIST"}',
    "https://provider.invalid/?request_token=DO_NOT_PERSIST&status=failed",
    "Authorization: Bearer DO_NOT_PERSIST",
])
def test_sensitive_message_redaction_preserves_context(text):
    from src.application.security import sanitize_error, sanitize_sensitive
    assert "DO_NOT_PERSIST" not in sanitize_error(DomainValidationError(text))
    assert "DO_NOT_PERSIST" not in sanitize_sensitive({"message": text})["message"]
    assert sanitize_error(DomainValidationError("invalid range")) == "invalid range"
    assert sanitize_sensitive({"accessToken": "DO_NOT_PERSIST"}) == {"accessToken": "[REDACTED]"}


def test_log_filter_redacts_formatted_arguments_and_traceback():
    import io
    import logging

    from src.application.security import RedactingLogFilter

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(RedactingLogFilter())
    logger = logging.getLogger("screener.phase1-verification")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info("job 42 stage provider api_secret=%s", "DO_NOT_PERSIST")
    try:
        raise RuntimeError("access_token=DO_NOT_PERSIST")
    except RuntimeError:
        logger.exception("job 42 failed")
    logger.removeHandler(handler)
    text = output.getvalue()
    assert "DO_NOT_PERSIST" not in text
    assert "job 42" in text
    assert "RuntimeError" in text



def test_unknown_quality_instrument_is_a_domain_error(tmp_path):
    market = repository(tmp_path)
    with pytest.raises(DomainValidationError, match="not registered"):
        market.record_quality_event("unknown", START, "missing_bar", "WARNING", {})



def test_worker_failure_and_event_api_redact_embedded_credentials(tmp_path):
    import json

    from flask import Flask

    from src.application.jobs import JobStore
    from src.application.web import create_operations_blueprint
    from src.application.worker import JobWorker

    jobs = JobStore(tmp_path / "jobs.db")
    job = jobs.submit("phase1-redaction", "validate", {})
    jobs.emit(job.job_id, "progress", {"stage": "provider", "message": "request_token=DO_NOT_PERSIST"})

    def invalid(payload):
        raise DomainValidationError("api_secret=DO_NOT_PERSIST invalid provider session")

    failed = JobWorker(jobs, "quality-review", {"validate": invalid}).run_once()
    assert "invalid provider session" in failed.last_error
    assert "DO_NOT_PERSIST" not in failed.last_error
    app = Flask(__name__)
    app.register_blueprint(create_operations_blueprint(jobs))
    client = app.test_client()
    path = f"/api/v2/operations/jobs/{job.job_id}/events"
    response = client.get(path)
    assert response.status_code == 200
    assert "DO_NOT_PERSIST" not in json.dumps(response.json)
    cursor = response.json["events"][0]["event_id"]
    continuation = client.get(path, headers={"Last-Event-ID": str(cursor)})
    assert all(event["event_id"] > cursor for event in continuation.json["events"])


def test_quality_readback_filters_and_pagination(tmp_path):
    from flask import Flask

    from src.application.catalog import ArtifactCatalog
    from src.application.market_web import create_market_blueprint

    market = repository(tmp_path)
    assert market.record_quality_event("stock", START, "missing_bar", "WARNING", {"expected": 1, "actual": 0, "message": "access_token=DO_NOT_PERSIST"})
    assert not market.record_quality_event("stock", START, "missing_bar", "WARNING", {"actual": 0, "expected": 1, "message": "access_token=DO_NOT_PERSIST"})
    market.record_quality_event("stock", START, "close_gap", "WARNING", {"expected": 100, "actual": 120})
    app = Flask(__name__)
    app.register_blueprint(create_market_blueprint(market, ArtifactCatalog(market.path)))
    client = app.test_client()
    path = "/api/v2/market/quality-events"
    filtered = client.get(path+"?instrument_id=stock&check_type=missing_bar&severity=WARNING")
    assert filtered.status_code == 200
    assert len(filtered.json["quality_events"]) == 1
    assert "DO_NOT_PERSIST" not in filtered.get_data(as_text=True)
    first = client.get(path+"?limit=1").json["quality_events"][0]
    second = client.get(path+"?limit=1&offset=1").json["quality_events"][0]
    assert first["event_id"] != second["event_id"]
    assert client.get(path+"?limit=0").status_code == 400
