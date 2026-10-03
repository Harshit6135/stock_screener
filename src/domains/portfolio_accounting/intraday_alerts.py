"""Durable, fill-free intraday stop-alert read model."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from src.platform_kernel import DomainValidationError, QualityStatus
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class _Lot(Protocol):
    instrument_id: str


class _Projection(Protocol):
    open_lots: tuple[_Lot, ...]


class _Ledger(Protocol):
    def projection(self, account_id: str) -> _Projection: ...


class _RiskProjectionReader(Protocol):
    def risk_projection(self, account_id: str) -> list[dict[str, object]]: ...


class _AlertPublisher(Protocol):
    def has(self, artifact_id: str) -> bool: ...

    def publish_json(self, category: str, artifact_id: str, payload: dict[str, object], *, quality: QualityStatus) -> object: ...


class IntradayStopAlerts:
    """Apply retained ATR stops to observations and publish immutable alerts."""

    def __init__(self, database: str | Path, ledger: _Ledger, risk_projections: _RiskProjectionReader, publisher: _AlertPublisher) -> None:
        self.database, self.ledger = Path(database), ledger
        self.risk_projections, self.publisher = risk_projections, publisher
        migrate_sqlite(self.database, "intraday_alerts", {1: (
            """CREATE TABLE IF NOT EXISTS intraday_stop_alerts (
                alert_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                price TEXT NOT NULL, stop_price TEXT NOT NULL,
                source TEXT NOT NULL, created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS intraday_alerts_account_time ON intraday_stop_alerts(account_id, observed_at)",
        )})

    def ingest(self, payload: dict[str, object]) -> dict[str, object]:
        required = {"account_id", "observations"}
        if not isinstance(payload, dict) or set(payload) != required or not isinstance(payload["account_id"], str) or not isinstance(payload["observations"], list) or not payload["observations"]:
            raise DomainValidationError("intraday observations require account_id and a non-empty list")
        account_id = str(payload["account_id"])
        projection = self.ledger.projection(account_id)
        held = {lot.instrument_id for lot in projection.open_lots}
        risk = [item for item in self.risk_projections.risk_projection(account_id)
                if item.get("stop_model") == "ATR"]
        alerts: list[dict[str, object]] = []
        for observation in payload["observations"]:
            if not isinstance(observation, dict) or set(observation) not in ({"instrument_id", "price", "observed_at"}, {"instrument_id", "price", "observed_at", "source"}):
                raise DomainValidationError("intraday observation fields are invalid")
            instrument_id = observation["instrument_id"]
            try:
                price = Decimal(str(observation["price"]))
                observed_at = datetime.fromisoformat(str(observation["observed_at"]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise DomainValidationError("intraday observation values are invalid") from exc
            if not isinstance(instrument_id, str) or not instrument_id.strip() or not price.is_finite() or price <= 0 or observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise DomainValidationError("intraday observation values are invalid")
            applicable = [item for item in risk if str(item["action_date"]) <= observed_at.date().isoformat()]
            latest = max(applicable, key=lambda item: str(item["action_date"]), default=None)
            stops = {str(item["instrument_id"]): Decimal(str(item["current_trailing_stop"])) * Decimal("0.97")
                     for item in latest["positions"]} if latest else {}
            if instrument_id in held and instrument_id not in stops:
                raise DomainValidationError("held stock is missing an ATR risk projection")
            stop = stops.get(instrument_id) if instrument_id in held else None
            if stop is None or price > stop:
                continue
            source = str(observation.get("source", "provider-tick"))
            definition = {"account_id": account_id, "instrument_id": instrument_id, "observed_at": observed_at.isoformat(), "price": str(price), "stop_price": str(stop), "source": source}
            alert_id = str(uuid5(NAMESPACE_URL, "intraday-stop-alert:" + hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()))
            alert = {"alert_id": alert_id, **definition}
            if not self.publisher.has(alert_id):
                self.publisher.publish_json("alerts/intraday-stops", alert_id, alert, quality=QualityStatus.PARTIAL)
            with sqlite_connection(self.database) as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO intraday_stop_alerts(alert_id, account_id, instrument_id, observed_at, price, stop_price, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (alert_id, account_id, instrument_id, observed_at.isoformat(), str(price), str(stop), source, datetime.now(UTC).isoformat()),
                )
            alerts.append(alert)
        return {"account_id": account_id, "alert_count": len(alerts), "alerts": alerts, "fills_created": 0}

    def read(self, account_id: str, limit: int = 100) -> list[dict[str, object]]:
        if not 1 <= limit <= 500:
            raise DomainValidationError("intraday alert limit must be 1..500")
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            rows = connection.execute("SELECT * FROM intraday_stop_alerts WHERE account_id=? ORDER BY observed_at DESC LIMIT ?", (account_id, limit)).fetchall()
        return [dict(row) for row in rows]
