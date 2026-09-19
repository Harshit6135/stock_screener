from datetime import date

from src.application import (
    JobStatus,
    JobStore,
    JobWorker,
    compare_execution_events,
    dashboard_visual_contract,
    next_tradable_session,
    restore_drill,
)
from src.application.sqlite import sqlite_connection
from src.platform_kernel import DomainValidationError


def test_execution_parity_includes_signal_and_fill_timestamps():
    event = {
        "event": "BUY",
        "instrument_id": "ABC",
        "side": "BUY",
        "units": 2,
        "signal_at": "2026-01-02T15:30:00+05:30",
        "executed_at": "2026-01-05T09:15:00+05:30",
    }
    assert compare_execution_events([event], [event])["parity"] is True
    changed = dict(event, executed_at="2026-01-06T09:15:00+05:30")
    assert compare_execution_events([event], [changed])["parity"] is False


def test_next_session_skips_holiday_and_missing_next_bar():
    assert next_tradable_session(date(2026, 1, 2), (date(2026, 1, 5), date(2026, 1, 7))) == date(
        2026, 1, 5
    )
    try:
        next_tradable_session(date(2026, 1, 7), (date(2026, 1, 7),))
    except DomainValidationError:
        pass
    else:
        raise AssertionError("missing next session must be explicit")


def test_long_running_handler_can_checkpoint_and_cancel(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    jobs.submit("cooperative", "long")

    def handler(payload, context):
        jobs.request_cancel(context.job_id)
        context.checkpoint()
        return {}

    result = JobWorker(jobs, "worker", {"long": handler}).run_once()
    assert result is not None and result.status == JobStatus.CANCELLED


def test_restore_drill_proves_backup_and_restored_readiness(tmp_path):
    source = tmp_path / "source.db"
    with sqlite_connection(source) as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('ok')")
    report = restore_drill(source, tmp_path / "drill")
    assert report["backup_ready"] is True
    assert report["restored_ready"] is True
    assert report["read_only_source"] is True


def test_dashboard_contract_covers_all_v4_workflows():
    html = "/app /actions /backtest /pipeline /portfolio"
    assert dashboard_visual_contract(html)["parity"] is True
