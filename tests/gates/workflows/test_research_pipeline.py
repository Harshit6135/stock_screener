from src.domains.operations import JobStore
from src.gates.workflows.research_pipeline import ResearchPipelineJobs


def test_pipeline_default_strategies_include_both_retained_branches(tmp_path):
    database = tmp_path / "system.db"
    jobs = JobStore(database)
    pipelines = ResearchPipelineJobs(database, jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-11"})
    assert pipeline["strategies"] == ["momentum", "positional_trend_following"]
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None
    assert claimed.payload["strategies"] == ["momentum"]
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None
    assert claimed.payload["universe"] == "SNAPSHOT_NIFTY500"


def test_pipeline_waits_for_inline_preparation_before_queuing_both_rankings(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit(
        {"start_date": "2026-09-07", "end_date": "2026-09-11", "orchestrate_data": True}
    )
    assert {stage["name"] for stage in pipeline["stages"]} == {"market:prepare", "advance"}
    assert pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})["deferred"] is True
    claimed = jobs.claim_next("worker-1")
    assert claimed.kind == "research.pipeline-prepare"
    jobs.complete(
        claimed.job_id, {"snapshot_id": "membership", "market_batches": 1}, claimed.claim_token
    )
    advanced = pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})
    research_stages = {
        stage["name"]: jobs.get(stage["job_id"])
        for stage in advanced["stages"]
        if stage["name"].startswith("research:")
    }
    assert set(research_stages) == {"research:factor-bulk", "research:event-signals"}
    factor = research_stages["research:factor-bulk"]
    event = research_stages["research:event-signals"]
    assert factor.kind == "research.rebuild-range"
    assert factor.payload["strategies"] == ["momentum"]
    assert event.kind == "research.positional-trend-build-range"
    assert event.payload["universe"] == "SNAPSHOT_NIFTY500"
    assert factor.payload["trading_dates"] == event.payload["trading_dates"]
    assert len(factor.payload["trading_dates"]) == 5
    assert (
        pipelines.advance({"pipeline_id": pipeline["pipeline_id"]})["stages"] == advanced["stages"]
    )


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
    assert not any(
        stage["name"].startswith("research:")
        for stage in pipelines.status(pipeline["pipeline_id"])["stages"]
    )


def test_pipeline_queues_both_ranking_branches_and_reports_progress(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-11"})
    assert [stage["name"] for stage in pipeline["stages"]] == [
        "research:event-signals",
        "research:factor-bulk",
    ]
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None
    assert claimed.kind == "research.rebuild-range"
    assert claimed.payload["strategies"] == ["momentum"]
    assert claimed.payload["trading_dates"] == ["2026-09-11"]
    jobs.complete(claimed.job_id, {"ok": True}, claimed.claim_token)
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None and claimed.kind == "research.positional-trend-build-range"
    jobs.complete(claimed.job_id, {"ok": True}, claimed.claim_token)
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "SUCCEEDED"
    assert pipelines.submit({"as_of_date": "2026-09-11"})["pipeline_id"] == pipeline["pipeline_id"]


def test_pipeline_retries_only_the_failed_stage(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["momentum"]})
    bulk = next(stage for stage in pipeline["stages"] if stage["name"] == "research:factor-bulk")
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None and claimed.kind == "research.rebuild-range"
    jobs.fail(claimed.job_id, "temporary provider failure", claimed.claim_token, retryable=False)
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "FAILED"

    retried = pipelines.retry_stage(pipeline["pipeline_id"], "research:factor-bulk")
    assert retried["retried_stage"] == "research:factor-bulk"
    assert jobs.get(bulk["job_id"]).status.value == "QUEUED"
    assert jobs.get(bulk["job_id"]).attempts == 0


def test_pipeline_cancel_propagates_to_queued_stages(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["momentum"]})
    result = pipelines.cancel(pipeline["pipeline_id"])
    assert result["cancelled_stages"] == ["research:factor-bulk"]
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "FAILED"


def test_pipeline_range_queues_one_job_with_weekday_sessions(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit(
        {"start_date": "2026-09-07", "end_date": "2026-09-11", "strategies": ["momentum"]}
    )
    assert [stage["name"] for stage in pipeline["stages"]] == ["research:factor-bulk"]
    job = jobs.get(pipeline["stages"][0]["job_id"])
    assert job.payload["trading_dates"] == [
        "2026-09-07",
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
    ]


def test_only_one_bulk_research_job_can_run_across_workers(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["momentum"]})
    pipelines.submit({"as_of_date": "2026-09-11", "strategies": ["momentum"]})
    running = jobs.claim_next("worker-one", lease_seconds=3600)
    assert running is not None and running.kind == "research.rebuild-range"
    assert jobs.claim_next("worker-two") is None
