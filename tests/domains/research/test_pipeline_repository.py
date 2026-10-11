from src.domains.research import ResearchPipelineRepository
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection


def test_pipeline_repository_persists_pipeline_and_stage_state_atomically(tmp_path):
    repository = ResearchPipelineRepository(tmp_path / "system.db")
    repository.create(
        pipeline_id="pipeline-1",
        fingerprint="fingerprint-1",
        as_of_date="2026-09-11",
        strategies_json='["momentum"]',
        created_at="2026-09-12T00:00:00+00:00",
        start_date="2026-09-11",
        end_date="2026-09-11",
        trading_dates_json='["2026-09-11"]',
        stages=[("research:factor-bulk", 12), ("advance", 13)],
    )

    assert repository.exists("pipeline-1")
    assert repository.pipeline("pipeline-1")["fingerprint"] == "fingerprint-1"
    assert [stage["stage_name"] for stage in repository.stages("pipeline-1")] == [
        "advance",
        "research:factor-bulk",
    ]
    with sqlite_connection(tmp_path / "system.db", read_only=True) as connection:
        versions = connection.execute(
            "SELECT version FROM system_schema_migrations "
            "WHERE namespace='research_pipeline' ORDER BY version"
        ).fetchall()
    assert [version[0] for version in versions] == [1]

    repository.set_stage_job("pipeline-1", "advance", 14)
    repository.set_trading_dates("pipeline-1", '["2026-09-10", "2026-09-11"]')
    repository.add_stages_if_missing("pipeline-1", [("research:factor-bulk", 99)])

    assert repository.pipeline("pipeline-1")["trading_dates_json"] == (
        '["2026-09-10", "2026-09-11"]'
    )
    assert {stage["stage_name"]: stage["job_id"] for stage in repository.stages("pipeline-1")} == {
        "advance": 14,
        "research:factor-bulk": 12,
    }


def test_pipeline_repository_rejects_missing_pipeline_reads(tmp_path):
    repository = ResearchPipelineRepository(tmp_path / "system.db")

    try:
        repository.pipeline("missing")
    except DomainValidationError as error:
        assert str(error) == "research pipeline was not found"
    else:
        raise AssertionError("missing pipeline read was accepted")
