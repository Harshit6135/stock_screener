from flask import Flask

from src.application.dashboard_web import create_dashboard_blueprint
from src.application.jobs import JobStore
from src.application.pipeline_jobs import ResearchPipelineJobs
from src.application.pipeline_web import create_pipeline_blueprint


def _complete_next(jobs):
    job = jobs.claim_next("test-worker")
    assert job is not None
    return jobs.complete(job.job_id, {"ok": True}, job.claim_token)


def test_pipeline_queues_one_bulk_job_and_reports_progress(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-11"})
    assert [stage["name"] for stage in pipeline["stages"]] == ["research:bulk"]
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None
    assert claimed.kind == "research.rebuild-range"
    assert claimed.payload["strategies"] == ["strategy1", "strategy2"]
    assert claimed.payload["trading_dates"] == ["2026-09-11"]
    jobs.complete(claimed.job_id, {"ok": True}, claimed.claim_token)
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "SUCCEEDED"
    assert pipelines.submit({"as_of_date": "2026-09-11"})["pipeline_id"] == pipeline["pipeline_id"]


def test_pipeline_api_accepts_bulk_research_requests(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    app = Flask(__name__)
    app.register_blueprint(create_pipeline_blueprint(pipelines))
    client = app.test_client()
    assert (
        client.post("/api/v2/pipelines/research", json={"as_of_date": "2026-09-11"}).status_code
        == 202
    )
    response = client.post(
        "/api/v2/pipelines/research",
        json={"as_of_date": "2026-09-11", "strategies": ["strategy1"]},
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
    assert "id='progress'" in page
    assert "id='stages'" in page
    assert "'/retry'" in page
    assert "'/cancel'" in page


def test_pipeline_retries_only_the_failed_stage(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["strategy1"]})
    bulk = next(stage for stage in pipeline["stages"] if stage["name"] == "research:bulk")
    claimed = jobs.claim_next("test-worker")
    assert claimed is not None and claimed.kind == "research.rebuild-range"
    jobs.fail(claimed.job_id, "temporary provider failure", claimed.claim_token, retryable=False)
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "FAILED"

    retried = pipelines.retry_stage(pipeline["pipeline_id"], "research:bulk")
    assert retried["retried_stage"] == "research:bulk"
    assert jobs.get(bulk["job_id"]).status.value == "QUEUED"
    assert jobs.get(bulk["job_id"]).attempts == 0


def test_pipeline_cancel_propagates_to_queued_stages(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["strategy1"]})
    result = pipelines.cancel(pipeline["pipeline_id"])
    assert result["cancelled_stages"] == ["research:bulk"]
    assert pipelines.status(pipeline["pipeline_id"])["status"] == "FAILED"


def test_pipeline_range_queues_one_job_with_weekday_sessions(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    pipeline = pipelines.submit(
        {"start_date": "2026-09-07", "end_date": "2026-09-11", "strategies": ["strategy1"]}
    )
    assert [stage["name"] for stage in pipeline["stages"]] == ["research:bulk"]
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
    pipelines.submit({"as_of_date": "2026-09-10", "strategies": ["strategy1"]})
    pipelines.submit({"as_of_date": "2026-09-11", "strategies": ["strategy1"]})
    running = jobs.claim_next("worker-one", lease_seconds=3600)
    assert running is not None and running.kind == "research.rebuild-range"
    assert jobs.claim_next("worker-two") is None
