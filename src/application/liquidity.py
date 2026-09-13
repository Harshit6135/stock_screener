"""Application handler for reproducible liquidity-universe publication."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from src.application.publication import ArtifactPublisher
from src.market_data import NormalizedBar
from src.platform_kernel import ArtifactManifest, DomainValidationError
from src.reference_data import Instrument, LiquidityUniversePolicy, build_liquidity_universe


def publish_liquidity_universe(
    publisher: ArtifactPublisher, payload: dict[str, Any]
) -> ArtifactManifest:
    """Validate a JSON job command and publish its immutable universe artifact."""
    as_of_date = _date(payload.get("as_of_date"), "as_of_date")
    policy = _policy(_mapping(payload.get("policy"), "policy"))
    instruments = tuple(
        _instrument(_mapping(value, "instruments entry"))
        for value in _list(payload.get("instruments"), "instruments")
    )
    bars = tuple(
        _bar(_mapping(value, "bars entry")) for value in _list(payload.get("bars"), "bars")
    )
    snapshot = build_liquidity_universe(instruments, bars, as_of_date, policy)
    return publisher.publish_json(
        "reference/liquidity_universes", str(snapshot.snapshot_id), snapshot.to_payload()
    )


def _policy(value: dict[str, Any]) -> LiquidityUniversePolicy:
    _only_keys(
        value,
        {
            "policy_id",
            "name",
            "lookback_sessions",
            "minimum_valid_sessions",
            "minimum_median_daily_turnover",
            "minimum_price",
        },
        "policy",
    )
    return LiquidityUniversePolicy(
        _uuid(value.get("policy_id"), "policy.policy_id"),
        _string(value.get("name"), "policy.name"),
        _integer(value.get("lookback_sessions"), "policy.lookback_sessions"),
        _integer(value.get("minimum_valid_sessions"), "policy.minimum_valid_sessions"),
        _decimal(
            value.get("minimum_median_daily_turnover"), "policy.minimum_median_daily_turnover"
        ),
        _decimal(value["minimum_price"], "policy.minimum_price")
        if "minimum_price" in value and value["minimum_price"] is not None
        else None,
    )


def _instrument(value: dict[str, Any]) -> Instrument:
    _only_keys(value, {"instrument_id", "isin", "symbol", "exchange"}, "instrument")
    return Instrument(
        _uuid(value.get("instrument_id"), "instrument.instrument_id"),
        _string(value.get("isin"), "instrument.isin"),
        _string(value.get("symbol"), "instrument.symbol"),
        _string(value.get("exchange"), "instrument.exchange"),
    )


def _bar(value: dict[str, Any]) -> NormalizedBar:
    _only_keys(
        value,
        {
            "instrument_id",
            "as_of_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "traded_value",
        },
        "bar",
    )
    return NormalizedBar(
        _string(value.get("instrument_id"), "bar.instrument_id"),
        _date(value.get("as_of_date"), "bar.as_of_date"),
        _decimal(value.get("open"), "bar.open"),
        _decimal(value.get("high"), "bar.high"),
        _decimal(value.get("low"), "bar.low"),
        _decimal(value.get("close"), "bar.close"),
        _integer(value.get("volume"), "bar.volume"),
        _decimal(value["traded_value"], "bar.traded_value")
        if "traded_value" in value and value["traded_value"] is not None
        else None,
    )


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DomainValidationError(f"{field} must be an object")
    return value


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise DomainValidationError(f"{field} must be a non-empty array")
    return value


def _only_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    if set(value) - allowed:
        raise DomainValidationError(f"{field} contains unsupported fields")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainValidationError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise DomainValidationError(f"{field} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainValidationError(f"{field} must be numeric") from exc
    if not parsed.is_finite():
        raise DomainValidationError(f"{field} must be finite")
    return parsed


def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DomainValidationError(f"{field} must be an ISO date") from exc


def _uuid(value: object, field: str) -> UUID:
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainValidationError(f"{field} must be a UUID") from exc
