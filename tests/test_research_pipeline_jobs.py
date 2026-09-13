from flask import Flask

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
        == 401
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
