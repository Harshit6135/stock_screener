from decimal import Decimal
from datetime import date
from flask import Flask

from src.application.dashboard_web import create_dashboard_blueprint
from src.application.jobs import JobStore, JobStatus
from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.worker import BackgroundWorker, JobWorker
from src.portfolio_engine import Candidate, MarketBar, PortfolioPolicy, PortfolioState, evaluate
from src.platform_kernel import DomainValidationError, Money


def test_pipeline_enforces_market_data_and_child_bar_jobs(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)

    pipeline = pipelines.submit({
        "start_date": "2026-09-07",
        "end_date": "2026-09-11",
        "strategies": ["strategy1"],
        "orchestrate_data": True,
    })

    # Only data jobs should be queued initially when orchestrate_data is True
    stage_names = {s["name"] for s in pipeline["stages"]}
    assert "reference:sync" in stage_names
    assert "market:refresh" in stage_names
    assert "reference:reconcile" in stage_names
    assert "advance" in stage_names
    assert not any(name.startswith("daily:") for name in stage_names)

    # An incomplete coordinator pass is deferred, rather than marked failed.
    deferred = pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})
    assert deferred["deferred"] is True

    # Complete reference:sync and reference:reconcile
    ref_sync = next(s for s in pipeline["stages"] if s["name"] == "reference:sync")
    claimed_sync = jobs.claim_next("worker-1")
    jobs.complete(claimed_sync.job_id, {"synced": 10}, claimed_sync.claim_token)

    # Market refresh schedules child bar jobs
    child_bar_job = jobs.submit("bar:INFY:2026-09-07:2026-09-11", "market.fetch-kite-bars", {"symbol": "INFY"})
    claimed_mkt = jobs.claim_next("worker-1")
    jobs.complete(claimed_mkt.job_id, {"job_ids": [child_bar_job.job_id], "scheduled_count": 1}, claimed_mkt.claim_token)

    ref_rec = next(s for s in pipeline["stages"] if s["name"] == "reference:reconcile")
    claimed_rec = jobs.claim_next("worker-1")
    jobs.complete(claimed_rec.job_id, {"reconciled": True}, claimed_rec.claim_token)

    # Child bar job is still QUEUED, so the coordinator remains deferred.
    assert pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})["deferred"] is True

    # Complete child bar job
    while True:
        claimed = jobs.claim_next("worker-1")
        if claimed is None:
            break
        jobs.complete(claimed.job_id, {"bars": 5}, claimed.claim_token)
        if claimed.job_id == child_bar_job.job_id:
            break

    # Now advance should succeed and queue daily stages!
    advanced = pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})
    daily_stages = [s for s in advanced["stages"] if s["name"].startswith("daily:")]
    assert len(daily_stages) == 5  # 5 trading days in the range
    assert advanced["market_data"]["succeeded"] == 1
    assert advanced["market_data"]["failed"] == 0


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
        if jobs.get(job.job_id).status == JobStatus.SUCCEEDED and bg.status()["processed_count"] == 1:
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
    bar = MarketBar("INFY", date(2026, 9, 8), Decimal(100), Decimal(105), Decimal(95), Decimal(102), 1000)
    candidate = Candidate("INFY", Decimal(80))

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

    for path in ["/app", "/actions", "/backtest", "/portfolio", "/pipeline"]:
        res = client.get(path)
        assert res.status_code == 200, f"failed for {path}"
        html = res.get_data(as_text=True)
        assert 'class="navbar"' in html
        assert 'Operator Token:' not in html
