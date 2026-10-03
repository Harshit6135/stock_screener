from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domains.market_data import NormalizedBar
from src.domains.operations import JobStatus
from src.domains.reference_data import (
    Instrument,
    LiquidityUniversePolicy,
    UniverseExclusionReason,
    build_liquidity_universe,
)
from src.gates.composition import ApplicationServices
from src.platform_kernel import ArtifactStore, DomainValidationError


def _instrument(symbol: str) -> Instrument:
    return Instrument(uuid4(), f"INE{uuid4().hex[:9].upper()}", symbol, "NSE")


AS_OF = date(2026, 3, 27)


def _bars(
    instrument: Instrument,
    *,
    count: int = 60,
    latest_volume: int = 20,
    latest_flat: bool = False,
    traded_value: Decimal | None = None,
) -> list[NormalizedBar]:
    records: list[NormalizedBar] = []
    for offset in range(count):
        session_date = AS_OF - timedelta(days=count - offset - 1)
        close = Decimal(100)
        is_latest = offset == count - 1
        if is_latest and latest_flat:
            opening = high = low = close
        else:
            opening, high, low = Decimal(99), Decimal(101), Decimal(98)
        records.append(
            NormalizedBar(
                str(instrument.instrument_id),
                session_date,
                opening,
                high,
                low,
                close,
                latest_volume if is_latest else 20,
                traded_value,
            )
        )
    return records


def _policy(**overrides: object) -> LiquidityUniversePolicy:
    values: dict[str, object] = {
        "policy_id": uuid4(),
        "name": "Liquidity v1",
        "lookback_sessions": 60,
        "minimum_valid_sessions": 54,
        "minimum_median_daily_turnover": Decimal(1500),
    }
    values.update(overrides)
    return LiquidityUniversePolicy(**values)  # type: ignore[arg-type]


def test_liquidity_universe_uses_median_turnover_and_publishes_audit_record(tmp_path):
    liquid = _instrument("LIQUID")
    snapshot = build_liquidity_universe([liquid], _bars(liquid), AS_OF, _policy())

    member = snapshot.members[0]
    assert snapshot.instrument_ids == (liquid.instrument_id,)
    assert member.eligible is True
    assert member.median_daily_turnover == Decimal(2000)
    assert member.exclusion_reasons == ()

    manifest = snapshot.publish(ArtifactStore(tmp_path))
    _, payload = ArtifactStore(tmp_path).read_json(manifest.category, manifest.artifact_id)
    assert payload["turnover_basis"] == "close_times_volume_proxy"
    assert payload["members"][0]["eligible"] is True


def test_liquidity_universe_accepts_reported_traded_value_but_never_mixes_bases():
    instrument = _instrument("REPORTED")
    reported_bars = _bars(instrument, traded_value=Decimal(2500))
    snapshot = build_liquidity_universe(
        [instrument],
        reported_bars,
        AS_OF,
        _policy(minimum_median_daily_turnover=Decimal(2200)),
    )

    assert snapshot.turnover_basis == "reported_traded_value"
    assert snapshot.members[0].median_daily_turnover == Decimal(2500)

    mixed_bars = [*reported_bars]
    mixed_bars[0] = NormalizedBar(
        str(instrument.instrument_id),
        mixed_bars[0].as_of_date,
        Decimal(99),
        Decimal(101),
        Decimal(98),
        Decimal(100),
        20,
    )
    with pytest.raises(DomainValidationError, match="must not mix turnover bases"):
        build_liquidity_universe([instrument], mixed_bars, AS_OF, _policy())


@pytest.mark.parametrize(
    ("kwargs", "reason", "flat_ohlc"),
    [
        ({"latest_volume": 0}, UniverseExclusionReason.ZERO_VOLUME, False),
        ({"latest_flat": True}, UniverseExclusionReason.FLAT_OHLC, True),
        ({"count": 53}, UniverseExclusionReason.INSUFFICIENT_HISTORY, False),
    ],
)
def test_liquidity_universe_records_simple_entry_exclusion_reasons(
    kwargs: dict[str, object], reason: UniverseExclusionReason, flat_ohlc: bool
):
    instrument = _instrument("ILLQ")
    snapshot = build_liquidity_universe([instrument], _bars(instrument, **kwargs), AS_OF, _policy())

    member = snapshot.members[0]
    assert member.eligible is False
    assert reason in member.exclusion_reasons
    assert member.flat_ohlc is flat_ohlc


def test_liquidity_universe_rejects_duplicate_identity_and_marks_missing_latest_bar():
    instrument = _instrument("MISSING")
    with pytest.raises(DomainValidationError, match="duplicate instruments"):
        build_liquidity_universe([instrument, instrument], _bars(instrument), AS_OF, _policy())

    snapshot = build_liquidity_universe(
        [instrument], _bars(instrument, count=60)[:-1], AS_OF, _policy()
    )
    assert snapshot.members[0].exclusion_reasons == (UniverseExclusionReason.MISSING_BAR,)


def _command() -> dict[str, object]:
    instrument_id = str(uuid4())
    as_of_date = date(2026, 3, 27)
    bars = []
    for offset in range(54):
        bars.append(
            {
                "instrument_id": instrument_id,
                "as_of_date": (as_of_date - timedelta(days=53 - offset)).isoformat(),
                "open": 99,
                "high": 101,
                "low": 98,
                "close": 100,
                "volume": 20,
            }
        )
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
        "bars": bars,
    }


def test_liquidity_universe_job_validates_command_and_catalogs_artifact(tmp_path):
    services = ApplicationServices.create(tmp_path)
    job = services.jobs.submit(
        "liquidity:2026-03-27",
        "research.build-liquidity-universe",
        _command(),
        max_attempts=1,
    )

    completed = services.worker.run_once()

    assert completed is not None
    assert completed.last_error is None, completed
    assert completed.status == JobStatus.SUCCEEDED
    assert completed.result is not None
    artifact_id = completed.result["artifact_id"]
    assert isinstance(artifact_id, str)
    assert services.catalog.has(artifact_id)
    _, payload = services.artifacts.read_json("reference/liquidity_universes", artifact_id)
    assert payload["members"][0]["eligible"] is True
    assert services.jobs.get(job.job_id) == completed
