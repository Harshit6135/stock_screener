from datetime import date

from flask import Flask

from src.application.market_repository import MarketRepository, TrackedInstrument
from src.application.reference_web import create_reference_blueprint
from src.platform_kernel import ArtifactStore


def test_token_lookup_uses_dated_assignments_and_flags_ambiguity(tmp_path):
    repository = MarketRepository(tmp_path / "market.db")
    repository.upsert_instruments(
        [
            TrackedInstrument("a", "INA", "AAA", "NSE", "10", date(2026, 1, 1)),
            TrackedInstrument("b", "INB", "BBB", "NSE", "20", date(2026, 1, 1)),
        ]
    )
    repository.upsert_instruments(
        [
            TrackedInstrument("a", "INA", "AAA", "NSE", "30", date(2026, 1, 2)),
            TrackedInstrument("b", "INB", "BBB", "NSE", "10", date(2026, 1, 2)),
        ]
    )
    repository.upsert_instruments(
        [TrackedInstrument("a", "INA", "AAA", "NSE", "9", date(2025, 12, 31))]
    )
    assert repository.instrument_by_id("a")["provider_token"] == "30"

    app = Flask(__name__)
    app.register_blueprint(create_reference_blueprint(ArtifactStore(tmp_path), repository))
    client = app.test_client()

    old = client.get("/api/v2/reference/tokens/10?as_of=2026-01-01").json
    assert [item["instrument_id"] for item in old["assignments"]] == ["a"]
    assert old["ambiguous"] is False

    current = client.get("/api/v2/reference/tokens/10?as_of=2026-01-02").json
    assert [item["instrument_id"] for item in current["assignments"]] == ["b"]
    assert current["assignments"][0]["observed_on"] == "2026-01-02"
    assert client.get("/api/v2/reference/tokens/10?as_of=invalid").status_code == 400
    assert client.get("/api/v2/reference/tokens/10?exchange=INVALID").status_code == 400

    history = client.get("/api/v2/reference/instruments/a/token-history").json
    assert [row["provider_token"] for row in history["observations"]] == ["30", "10", "9"]
    assert [row["changed"] for row in history["observations"]] == [True, True, False]
    assert history["observations"][0]["previous_token"] == "10"
    assert (
        client.get("/api/v2/reference/instruments/a/token-history?limit=1&offset=1").json[
            "observations"
        ][0]["provider_token"]
        == "10"
    )
    assert client.get("/api/v2/reference/instruments/missing/token-history").status_code == 404
    assert client.get("/api/v2/reference/instruments/a/token-history?limit=501").status_code == 400

    repository.upsert_instruments(
        [TrackedInstrument("c", "INC", "CCC", "BSE", "10", date(2026, 1, 2))]
    )
    assert client.get("/api/v2/reference/tokens/10").json["ambiguous"] is True
    assert [
        item["instrument_id"]
        for item in client.get("/api/v2/reference/tokens/10?exchange=NSE").json["assignments"]
    ] == ["b"]
