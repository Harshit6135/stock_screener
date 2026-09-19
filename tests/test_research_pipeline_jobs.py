from flask import Flask

from src.application.dashboard_web import create_dashboard_blueprint
from src.application.jobs import JobStore
from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.pipeline_web import create_pipeline_blueprint


def _complete_next(jobs):
    job = jobs.claim_next("test-worker")
    assert job is not None
    return jobs.complete(job.job_id, {"ok": True}, job.claim_token)


def test_pipeline_queues_daily_then_weekly_jobs_and_reports_progress(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-11"})
    assert [stage["name"] for stage in pipeline["stages"]] == [
        "advance",
        "daily:strategy1",
        "daily:strategy2",
    ]
    _complete_next(jobs)
    _complete_next(jobs)
    advance = jobs.claim_next("test-worker")
    assert advance.kind == "research.pipeline-advance"
    result = pipelines.advance(advance.payload)
    jobs.complete(advance.job_id, result, advance.claim_token)
    assert {stage["name"] for stage in pipelines.status(pipeline["pipeline_id"])["stages"]} == {
        "advance",
        "daily:strategy1",
        "daily:strategy2",
        "weekly:strategy1",
        "weekly:strategy2",
    }
    _complete_next(jobs)
    _complete_next(jobs)
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "SUCCEEDED"
    assert pipelines.submit({"as_of_date": "2026-09-11"})["pipeline_id"] == pipeline["pipeline_id"]


def test_pipeline_api_is_operator_protected(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    app = Flask(__name__)
    app.config["OPERATOR_TOKEN"] = "test-secret"
    app.register_blueprint(create_pipeline_blueprint(pipelines))
    client = app.test_client()
    assert (
        client.post("/api/v2/pipelines/research", json={"as_of_date": "2026-09-11"}).status_code
        == 202
    )
    response = client.post(
        "/api/v2/pipelines/research",
        json={"as_of_date": "2026-09-11", "strategies": ["strategy1"]},
        headers={"X-Operator-Token": "test-secret"},
    )
    assert response.status_code == 202
    assert (
        client.get(f"/api/v2/pipelines/research/{response.json['pipeline_id']}").status_code == 200
    )


def test_pipeline_browser_renders_progress_and_recovery_controls():
    app = Flask(__name__)
    app.register_blueprint(create_dashboard_blueprint())
    response = app.test_client().get("/pipeline")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id=\'progress\'' in page
    assert 'id=\'stages\'' in page
    assert "'/retry'" in page
    assert "'/cancel'" in page


def test_pipeline_retries_only_the_failed_stage(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["strategy1"]})
    daily = next(stage for stage in pipeline["stages"] if stage["name"] == "daily:strategy1")
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None and claimed.kind == "research.calculate-day"
    jobs.fail(claimed.job_id, "temporary provider failure", claimed.claim_token, retryable=False)
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "FAILED"

    retried = pipelines.retry_stage(pipeline["pipeline_id"], "daily:strategy1")
    assert retried["retried_stage"] == "daily:strategy1"
    assert jobs.get(daily["job_id"]).status.value == "QUEUED"
    assert jobs.get(daily["job_id"]).attempts == 0


def test_pipeline_cancel_propagates_to_queued_stages(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["strategy1"]})
    result = pipelines.cancel(pipeline["pipeline_id"])
    assert result["cancelled_stages"] == ["advance", "daily:strategy1"]
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "FAILED"


def test_pipeline_range_queues_weekday_sessions_and_friday_rankings(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"start_date": "2026-09-07", "end_date": "2026-09-11", "strategies": ["strategy1"]})
    names = {stage["name"] for stage in pipeline["stages"]}
    assert "daily:strategy1:2026-09-07" in names
    assert "daily:strategy1:2026-09-11" in names
    assert "daily:strategy1:2026-09-12" not in names
    for _ in range(5):
        _complete_next(jobs)
    advance = jobs.claim_next("test-worker")
    assert advance is not None
    result = pipelines.advance(advance.payload)
    jobs.complete(advance.job_id, result, advance.claim_token)
    assert "weekly:strategy1:2026-09-11" in {stage["name"] for stage in pipelines.status(pipeline["pipeline_id"])["stages"]}


def test_pipeline_coordinator_defers_without_busy_loop_while_daily_job_runs(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["strategy1"]})
    daily = jobs.claim_next("daily-worker", lease_seconds=3600)
    assert daily is not None and daily.kind == "research.calculate-day"
    coordinator = jobs.claim_next("coordinator-worker")
    assert coordinator is not None and coordinator.kind == "research.pipeline-advance"
    result = pipelines.advance(coordinator.payload)
    jobs.complete(coordinator.job_id, result, coordinator.claim_token)
    assert result["deferred"] is True
    assert jobs.claim_next("coordinator-worker") is None
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "RUNNING"
