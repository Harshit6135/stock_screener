from flask import Flask

from src.domains.operations import JobStore
from src.gates.http.pipeline import create_pipeline_blueprint
from src.gates.workflows.research_pipeline import ResearchPipelineJobs


def test_pipeline_api_accepts_bulk_research_requests(tmp_path):
    jobs = JobStore(tmp_path / "system.db")
    pipelines = ResearchPipelineJobs(tmp_path / "system.db", jobs)
    app = Flask(__name__)
    app.register_blueprint(create_pipeline_blueprint(pipelines))
    client = app.test_client()
    assert (
        client.post("/api/pipelines/research", json={"as_of_date": "2026-09-11"}).status_code
        == 202
    )
    response = client.post(
        "/api/pipelines/research",
        json={"as_of_date": "2026-09-11", "strategies": ["momentum"]},
    )
    assert response.status_code == 202
    assert (
        client.get(f"/api/pipelines/research/{response.json['pipeline_id']}").status_code == 200
    )
