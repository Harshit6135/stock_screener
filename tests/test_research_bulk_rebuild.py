from datetime import date, timedelta

from src.application.catalog import ArtifactCatalog
from src.application.publication import ArtifactPublisher
from src.application.research_jobs import ResearchJobs
from src.application.sqlite import sqlite_connection
from src.platform_kernel import ArtifactStore


class _Runtime:
    def strategy_ids(self):
        return ("strategy1",)

    def revision(self, _strategy_id):
        return {
            "revision_id": "revision-1",
            "definition": {"score": {"factor_modifiers": []}},
        }

    def factor_weights(self, _strategy_id):
        return {"trend": 1.0}

    def benchmark(self, _strategy_id):
        return None

    def compute_series(self, _strategy_id, bars, _benchmark):
        return {
            bar["as_of_date"]: {
                "factors": {"trend": float(bar["close"])},
                "penalty": 1.0,
                "penalty_reasons": [],
            }
            for bar in bars
        }

    def cross_section(self, _strategy_id, _values):
        return None


class _Market:
    def __init__(self):
        start = date(2025, 1, 6)
        self.values = {}
        for instrument, symbol, offset in (("a", "AAA", 10), ("b", "BBB", 20)):
            bars = [
                {
                    "as_of_date": (start + timedelta(days=index)).isoformat(),
                    "close": offset + index,
                    "snapshot_id": f"{instrument}-{index}",
                }
                for index in range(5)
            ]
            self.values[instrument] = (
                bars,
                {"isin": f"INE-{instrument}", "symbol": symbol},
            )

    def histories(self, _start, _end):
        return self.values


class _Context:
    def __init__(self):
        self.progress = []

    def checkpoint(self, *, progress=None):
        if progress:
            self.progress.append(progress)


def test_bulk_rebuild_calculates_each_stage_and_persists_range(tmp_path):
    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    research = ResearchJobs(database, _Market(), publisher, _Runtime())
    context = _Context()
    sessions = [f"2025-01-{day:02d}" for day in range(6, 11)]

    result = research.rebuild_range(
        {
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "strategies": ["strategy1"],
            "trading_dates": sessions,
        },
        context,
    )

    assert result["execution_model"] == "bulk-staged-vectorized"
    assert result["strategies"]["strategy1"]["scored_rows"] == 10
    assert result["weekly_rankings"] == 1
    assert {item["stage"] for item in context.progress} == {
        "loading_market_history",
        "indicators",
        "percentiles",
        "scores",
        "rankings",
    }
    with sqlite_connection(database, read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_daily_scores").fetchone()[0] == 10
        assert (
            connection.execute("SELECT COUNT(*) FROM research_weekly_rankings").fetchone()[0] == 2
        )
