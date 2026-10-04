from datetime import date, timedelta
from uuid import uuid4

from flask import Flask

from run import create_app
from src.gates.http.reference import create_reference_blueprint
from src.gates.repositories import MarketRepository, TrackedInstrument
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
    old = client.get("/api/reference/tokens/10?as_of=2026-01-01").json
    assert [item["instrument_id"] for item in old["assignments"]] == ["a"]
    assert old["ambiguous"] is False
    current = client.get("/api/reference/tokens/10?as_of=2026-01-02").json
    assert [item["instrument_id"] for item in current["assignments"]] == ["b"]
    assert current["assignments"][0]["observed_on"] == "2026-01-02"
    assert client.get("/api/reference/tokens/10?as_of=invalid").status_code == 400
    assert client.get("/api/reference/tokens/10?exchange=INVALID").status_code == 400
    history = client.get("/api/reference/instruments/a/token-history").json
    assert [row["provider_token"] for row in history["observations"]] == ["30", "10", "9"]
    assert [row["changed"] for row in history["observations"]] == [True, True, False]
    assert history["observations"][0]["previous_token"] == "10"
    assert (
        client.get("/api/reference/instruments/a/token-history?limit=1&offset=1").json[
            "observations"
        ][0]["provider_token"]
        == "10"
    )
    assert client.get("/api/reference/instruments/missing/token-history").status_code == 404
    assert client.get("/api/reference/instruments/a/token-history?limit=501").status_code == 400
    repository.upsert_instruments(
        [TrackedInstrument("c", "INC", "CCC", "NSE", "10", date(2026, 1, 2))]
    )
    assert client.get("/api/reference/tokens/10").json["ambiguous"] is True
    assert [
        item["instrument_id"]
        for item in client.get("/api/reference/tokens/10?exchange=NSE").json["assignments"]
    ] == ["b"]


def _command() -> dict[str, object]:
    instrument_id = str(uuid4())
    as_of_date = date(2026, 3, 27)
    return {
        "as_of_date": as_of_date.isoformat(),
        "policy": {
            "policy_id": str(uuid4()),
            "name": "Liquidity v1",
            "lookback_sessions": 60,
            "minimum_valid_sessions": 54,
            "minimum_median_daily_turnover": 1500,
        },
        "instruments": [
            {
                "instrument_id": instrument_id,
                "isin": "INE000000001",
                "symbol": "ABC",
                "exchange": "NSE",
            }
        ],
        "bars": [
            {
                "instrument_id": instrument_id,
                "as_of_date": (as_of_date - timedelta(days=53 - offset)).isoformat(),
                "open": 99,
                "high": 101,
                "low": 98,
                "close": 100,
                "volume": 20,
            }
            for offset in range(54)
        ],
    }


def test_reference_api_reads_checksum_verified_liquidity_universe(tmp_path):

    class TestConfig:
        TESTING = True
        SECRET_KEY = "test"
        DATA_DIRECTORY = tmp_path

    app = create_app(TestConfig)
    services = app.extensions["screener_services"]
    job = services.jobs.submit(
        "liquidity:2026-03-27", "research.build-liquidity-universe", _command(), max_attempts=1
    )
    completed = services.worker.run_once()
    assert completed is not None and completed.result is not None
    response = app.test_client().get(
        f"/api/reference/liquidity-universes/{completed.result['artifact_id']}"
    )
    assert job.job_id == completed.job_id
    assert response.status_code == 200
    assert response.json["artifact"]["quality"] == "COMPLETE"
    assert response.json["universe"]["members"][0]["eligible"] is True


def test_reference_api_publishes_macro_snapshot(tmp_path):
    from flask import Flask

    from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
    from src.gates.http.reference import create_reference_blueprint
    from src.platform_kernel import ArtifactStore

    database = tmp_path / "system.db"
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / "artifacts"), ArtifactCatalog(database))
    app = Flask(__name__)
    app.register_blueprint(
        create_reference_blueprint(ArtifactStore(tmp_path / "artifacts"), publisher=publisher)
    )
    client = app.test_client()
    body = {"as_of_date": "2026-09-10", "values": {"vix": "18.5"}}
    assert client.post("/api/reference/macro-indicators", json=body).status_code == 201
    response = client.post("/api/reference/macro-indicators", json=body)
    assert response.status_code == 201
    artifact_id = response.json["artifact_id"]
    _, stored = publisher.store.read_json("reference/macro-indicators", artifact_id)
    assert stored["values"]["vix"] == "18.5"
    cap = client.post(
        "/api/reference/market-capitalization",
        json={"as_of_date": "2026-09-10", "values": {"instrument-a": "5000000000"}},
    )
    fundamentals = client.post(
        "/api/reference/fundamentals",
        json={
            "as_of_date": "2026-09-10",
            "values": {"instrument-a": {"eps": "12.5", "debt_equity": "0.4"}},
        },
    )
    assert cap.status_code == fundamentals.status_code == 201
    free_float = client.post(
        "/api/reference/market-capitalization",
        json={
            "as_of_date": "2026-09-10",
            "values": {"instrument-b": {"market_cap": "1000", "free_float": "0.25"}},
        },
    )
    assert free_float.status_code == 201
    assert (
        publisher.store.read_json(
            "reference/market-capitalization", free_float.json["artifact_id"]
        )[1]["values"]["instrument-b"]["free_float"]
        == "0.25"
    )
    assert (
        publisher.store.read_json("reference/fundamentals", fundamentals.json["artifact_id"])[1][
            "values"
        ]["instrument-a"]["eps"]
        == "12.5"
    )
    readback = client.get(f"/api/reference/fundamentals/{fundamentals.json['artifact_id']}")
    assert readback.status_code == 200
    assert readback.json["artifact"]["category"] == "reference/fundamentals"
    assert client.get("/api/reference/fundamentals/missing").status_code == 404
