from datetime import date

from src.application.market_repository import MarketRepository
from src.application.universe_jobs import UniverseJobs


def _members(*items: tuple[str, str, str]):
    return [
        {"isin": isin, "symbol": symbol, "company_name": symbol + " Ltd",
         "industry": "Industry", "series": series}
        for isin, symbol, series in items
    ]


def test_snapshot_is_insert_only_and_as_of_selection_is_deterministic(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    first = repository.create_universe_snapshot(
        snapshot_id="first", index_name="NIFTY 500", snapshot_date=date(2026, 1, 2),
        source_url="https://example.test/one", raw_csv=b"one",
        members=_members(("INE001", "ONE", "EQ")),
    )
    reused = repository.create_universe_snapshot(
        snapshot_id="different", index_name="NIFTY 500", snapshot_date=date(2026, 1, 2),
        source_url="https://example.test/two", raw_csv=b"two",
        members=_members(("INE002", "TWO", "BE")),
    )
    assert reused["snapshot_id"] == first["snapshot_id"] == "first"
    assert repository.universe_snapshot_as_of("NIFTY 500", date(2025, 1, 1))["earliest_fallback"]


def test_snapshot_diff_captures_membership_and_series_changes(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    repository.create_universe_snapshot(snapshot_id="old", index_name="NIFTY 500", snapshot_date=date(2026, 1, 1), source_url="https://example.test", raw_csv=b"old", members=_members(("INE001", "ONE", "EQ"), ("INE002", "TWO", "EQ")))
    repository.create_universe_snapshot(snapshot_id="new", index_name="NIFTY 500", snapshot_date=date(2026, 1, 2), source_url="https://example.test", raw_csv=b"new", members=_members(("INE001", "ONE", "BE"), ("INE003", "THREE", "EQ")))
    diff = repository.universe_snapshot_diff("old", "new")
    assert [item["isin"] for item in diff["additions"]] == ["INE003"]
    assert [item["isin"] for item in diff["removals"]] == ["INE002"]
    assert diff["series_transitions"] == [{"isin": "INE001", "from": "EQ", "to": "BE"}]


def test_daily_collection_reuses_snapshot_without_a_second_download(tmp_path):
    class Client:
        calls = 0

        def nifty_500_csv(self):
            self.calls += 1
            return "https://example.test/nifty500.csv", (
                b"Company Name,Industry,Symbol,Series,ISIN Code\nOne Ltd,Tech,ONE,EQ,INE001\n"
            )

    client = Client()
    job = UniverseJobs(MarketRepository(tmp_path / "market.db"), client,
                       collection_date=lambda: date(2026, 1, 2))
    first = job.download_nifty500_constituents({"snapshot_date": "2026-01-02"})
    second = job.download_nifty500_constituents({"snapshot_date": "2026-01-02"})
    assert first["status"] == "stored"
    assert second["status"] == "reused"
    assert second["snapshot_id"] == first["snapshot_id"]
    assert client.calls == 1
