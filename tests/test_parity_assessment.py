from datetime import date
from decimal import Decimal

from flask import Flask

from src.application.dashboard_web import create_dashboard_blueprint
from src.application.jobs import JobStatus, JobStore
from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.worker import BackgroundWorker, JobWorker
from src.platform_kernel import Money
from src.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState, evaluate


def test_pipeline_waits_for_inline_preparation_before_queuing_both_rankings(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"start_date": "2026-09-07", "end_date": "2026-09-11",
                                 "orchestrate_data": True})
    assert {stage["name"] for stage in pipeline["stages"]} == {"market:prepare", "advance"}
    assert pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})["deferred"] is True
    claimed = jobs.claim_next("worker-1")
    assert claimed.kind == "research.pipeline-prepare"
    jobs.complete(claimed.job_id, {"snapshot_id": "membership", "market_batches": 1}, claimed.claim_token)
    advanced = pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})
    research_stages = {stage["name"]: jobs.get(stage["job_id"])
                       for stage in advanced["stages"] if stage["name"].startswith("research:")}
    assert set(research_stages) == {"research:factor-bulk", "research:event-signals"}
    factor = research_stages["research:factor-bulk"]
    event = research_stages["research:event-signals"]
    assert factor.kind == "research.rebuild-range"
    assert factor.payload["strategies"] == ["momentum"]
    assert event.kind == "research.positional-trend-build-range"
    assert event.payload["universe"] == "SNAPSHOT_NIFTY500"
    assert factor.payload["trading_dates"] == event.payload["trading_dates"]
    assert len(factor.payload["trading_dates"]) == 5
    assert pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})["stages"] == advanced["stages"]


def test_failed_preparation_does_not_queue_rankings(tmp_path):
    import pytest

    from src.platform_kernel import DomainValidationError
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-11", "orchestrate_data": True})
    claimed = jobs.claim_next("worker-1")
    jobs.request_cancel(claimed.job_id)
    jobs.heartbeat(claimed.job_id, claimed.claim_token)
    with pytest.raises(DomainValidationError, match="failed data stage"):
        pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})
    assert not any(stage["name"].startswith("research:")
                   for stage in pipelines.status(pipeline["pipeline_id"])["stages"])


def test_background_worker_lifecycle_and_status(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    job = jobs.submit("test:bg:1", "test.task", {"val": 42})
    handled = []

    def handle_task(payload):
        handled.append(payload["val"])
        return {"processed": True}

    worker = JobWorker(jobs, "test-bg-worker", {"test.task": handle_task})
    bg = BackgroundWorker(worker, poll_interval=0.05)

    assert not bg.is_alive
    st = bg.status()
    assert st["running"] is False
    assert st["processed_count"] == 0

    bg.start()
    assert bg.is_alive

    import time

    # Wait for background thread to process job
    for _ in range(50):
        if (
            jobs.get(job.job_id).status == JobStatus.SUCCEEDED
            and bg.status()["processed_count"] == 1
        ):
            break
        time.sleep(0.05)

    assert handled == [42]
    completed_job = jobs.get(job.job_id)
    assert completed_job.status == JobStatus.SUCCEEDED
    st = bg.status()
    assert st["processed_count"] == 1
    bg.stop(timeout=2.0)
    assert not bg.is_alive


def test_portfolio_policy_backtest_options():
    # Verify check_daily_sl and mid_week_buy and WEEKLY rebalance frequency
    policy = PortfolioPolicy(
        max_positions=10,
        exit_score=Decimal(40),
        rebalance_frequency="BIWEEKLY",
        check_daily_sl=False,
        mid_week_buy=False,
        pyramid_fraction=Decimal("0.5"),
    )
    assert policy.rebalance_frequency == "BIWEEKLY"
    assert policy.check_daily_sl is False
    assert policy.mid_week_buy is False
    assert policy.pyramid_fraction == Decimal("0.5")

    # In evaluate:
    # When is_rebalance_day is False and mid_week_buy is False, candidates should not be bought
    state = PortfolioState(Money(Decimal(100000)))
    bar = MarketBar(
        "INFY", date(2026, 9, 8), Decimal(100), Decimal(105), Decimal(95), Decimal(102), 1000
    )
    candidate = Candidate("INFY", Decimal(80), atr=Decimal(5))

    decisions, next_state = evaluate(
        state,
        policy,
        [candidate],
        {"INFY": bar},
        is_rebalance_day=False,
    )
    assert len(next_state.holdings) == 0
    assert decisions[0].type.value == "NO_ACTION"

    # On rebalance day, candidate IS bought
    decisions, next_state = evaluate(
        state,
        policy,
        [candidate],
        {"INFY": bar},
        is_rebalance_day=True,
    )
    assert len(decisions) == 1
    assert decisions[0].type.value == "BUY"


def test_dashboard_web_routes_render():
    app = Flask(__name__)
    app.register_blueprint(create_dashboard_blueprint())
    client = app.test_client()

    for path in ["/", "/actions", "/backtest", "/pipeline", "/rankings", "/universe", "/settings", "/logs"]:
        res = client.get(path)
        assert res.status_code == 200, f"failed for {path}"
        html = res.get_data(as_text=True)
        assert 'class="sidebar"' in html
    for path in ["/app", "/portfolio"]:
        assert client.get(path).status_code == 302
