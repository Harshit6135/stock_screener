from datetime import date

from src.application import ArtifactCatalog
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.platform_kernel import ArtifactStore


class MarketStub:
    def histories(self, start_date, end_date):
        return {
            key: (
                [
                    {
                        "instrument_id": key,
                        "as_of_date": end_date.isoformat(),
                        "snapshot_id": f"market-{key}",
                    }
                ],
                {"symbol": key, "isin": f"INE-{key}"},
            )
            for key in ("A", "B")
        }


def test_recomputation_removes_stale_daily_and_weekly_members(tmp_path, monkeypatch):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    research = ResearchJobs(database, MarketStub(), publisher)
    include_b = True

    def factors(bars):
        if bars[0]["instrument_id"] == "B" and not include_b:
            return None
        return {
            "factors": {
                key: 50.0 for key in ("trend", "momentum", "efficiency", "volume", "structure")
            },
            "penalty": 1.0,
            "penalty_reasons": [],
        }

    monkeypatch.setattr("src.application.research_jobs.strategy1_factors", factors)
    day = date(2026, 9, 4)
    research.calculate_strategy1_day({"as_of_date": day.isoformat()})
    research.rank_week({"week_end": day.isoformat()})
    assert len(research.top_rankings(day)) == 2

    include_b = False
    research.calculate_strategy1_day({"as_of_date": day.isoformat()})
    research.rank_week({"week_end": day.isoformat()})
    assert [row["symbol"] for row in research.top_rankings(day)] == ["A"]
