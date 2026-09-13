"""Guarded, read-only import of a v3 personal SQLite portfolio snapshot."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.application.market_repository import MarketRepository
from src.application.publication import ArtifactPublisher
from src.application.sqlite import migrate_sqlite, sqlite_connection
from src.execution_gateway import Ledger
from src.platform_kernel import DomainValidationError, Money, QualityStatus, Quantity
from src.portfolio_accounting import Fill, FillSide


class LegacyPortfolioImporter:
    """Import only an auditable v3 holding snapshot; never modify its source DB."""

    def __init__(
        self,
        database: str | Path,
        market: MarketRepository,
        ledger: Ledger,
        publisher: ArtifactPublisher,
    ) -> None:
        self.database, self.market, self.ledger, self.publisher = (
            Path(database),
            market,
            ledger,
            publisher,
        )
        migrate_sqlite(
            self.database,
            "legacy_portfolio_import",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS legacy_portfolio_imports (
                        import_id TEXT PRIMARY KEY, account_id TEXT NOT NULL UNIQUE,
                        source_digest TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                        artifact_id TEXT NOT NULL UNIQUE, resulting_ledger_version INTEGER NOT NULL,
                        imported_at TEXT NOT NULL)""",
                )
            },
        )

    @staticmethod
    def _source(path_value: object) -> Path:
        if not isinstance(path_value, str) or not path_value.strip():
            raise DomainValidationError("legacy_path is required")
        path = Path(path_value).resolve()
        if not path.is_file() or path.suffix.lower() != ".db":
            raise DomainValidationError("legacy_path must name an existing SQLite database")
        return path

    def _snapshot(
        self, path: Path, requested_date: object | None
    ) -> tuple[date, list[dict[str, object]], Decimal]:
        try:
            with sqlite_connection(path, read_only=True, row_factory=True) as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                required = {"investment_holdings", "investment_summary"}
                if not required.issubset(tables):
                    raise DomainValidationError("legacy database lacks required portfolio tables")
                if requested_date is None:
                    row = connection.execute(
                        "SELECT MAX(date) AS date FROM investment_holdings"
                    ).fetchone()
                    if row is None or row["date"] is None:
                        raise DomainValidationError("legacy database has no holding snapshot")
                    snapshot_date = date.fromisoformat(str(row["date"]))
                else:
                    snapshot_date = date.fromisoformat(str(requested_date))
                holdings = [
                    dict(row)
                    for row in connection.execute(
                        """SELECT symbol, entry_date, entry_price, avg_price, units
                           FROM investment_holdings WHERE date=? ORDER BY symbol""",
                        (snapshot_date.isoformat(),),
                    )
                ]
                summary = connection.execute(
                    """SELECT remaining_capital FROM investment_summary
                       WHERE date<=? ORDER BY date DESC LIMIT 1""",
                    (snapshot_date.isoformat(),),
                ).fetchone()
        except (OSError, ValueError) as exc:
            raise DomainValidationError("legacy database snapshot is invalid") from exc
        if not holdings or summary is None or summary["remaining_capital"] is None:
            raise DomainValidationError("legacy snapshot lacks holdings or remaining capital")
        cash = Decimal(str(summary["remaining_capital"]))
        if cash < 0:
            raise DomainValidationError("legacy snapshot has negative remaining capital")
        return snapshot_date, holdings, cash

    def preview(self, payload: dict[str, Any]) -> dict[str, object]:
        if (
            not isinstance(payload, dict)
            or set(payload) - {"legacy_path", "snapshot_date"}
            or "legacy_path" not in payload
        ):
            raise DomainValidationError(
                "legacy preview requires legacy_path and optional snapshot_date"
            )
        path = self._source(payload["legacy_path"])
        snapshot_date, holdings, cash = self._snapshot(path, payload.get("snapshot_date"))
        resolved: list[dict[str, object]] = []
        unresolved: list[str] = []
        cost = Decimal(0)
        for holding in holdings:
            symbol = str(holding["symbol"])
            identity = None
            for exchange in ("NSE", "BSE"):
                try:
                    identity = self.market.instrument(symbol, exchange)
                    break
                except DomainValidationError:
                    continue
            if identity is None:
                unresolved.append(symbol)
                continue
            units = int(str(holding["units"]))
            unit_cost = Decimal(str(holding["avg_price"] or holding["entry_price"]))
            if units < 1 or unit_cost <= 0:
                raise DomainValidationError(f"legacy holding {symbol} has invalid units or cost")
            cost += unit_cost * units
            resolved.append(
                {
                    "instrument_id": identity["instrument_id"],
                    "symbol": symbol,
                    "exchange": identity["exchange"],
                    "entry_date": str(holding["entry_date"]),
                    "units": units,
                    "unit_cost": str(unit_cost),
                }
            )
        return {
            "source_digest": hashlib.sha256(path.read_bytes()).hexdigest(),
            "snapshot_date": snapshot_date.isoformat(),
            "resolved_holdings": resolved,
            "unresolved_symbols": unresolved,
            "remaining_cash": str(cash),
            "holding_cost": str(cost),
            "opening_cash_required": str(cash + cost),
            "limitations": [
                "imports only the latest v3 holding snapshot and cash projection",
                "historical realised P&L and individual sell history are unavailable in v3 holdings",
                "unresolved symbols must be reconciled before import",
            ],
        }

    def import_account(self, payload: dict[str, Any]) -> dict[str, object]:
        if (
            not isinstance(payload, dict)
            or set(payload) - {"account_id", "legacy_path", "snapshot_date"}
            or not {"account_id", "legacy_path"}.issubset(payload)
        ):
            raise DomainValidationError(
                "legacy import requires account_id, legacy_path and optional snapshot_date"
            )
        account_id = payload["account_id"]
        if not isinstance(account_id, str) or not account_id.strip():
            raise DomainValidationError("account_id is invalid")
        preview = self.preview(
            {"legacy_path": payload["legacy_path"], "snapshot_date": payload.get("snapshot_date")}
        )
        if preview["unresolved_symbols"]:
            raise DomainValidationError(
                "legacy import has unresolved symbols; reconcile before importing"
            )
        import_id = str(
            uuid5(
                NAMESPACE_URL,
                f"legacy-portfolio:{account_id}:{preview['source_digest']}:{preview['snapshot_date']}",
            )
        )
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            existing = connection.execute(
                "SELECT * FROM legacy_portfolio_imports WHERE import_id=?", (import_id,)
            ).fetchone()
        if existing is not None:
            return {"import_id": import_id, "status": "IMPORTED", **dict(existing)}
        opening_cash = Money(Decimal(str(preview["opening_cash_required"])))
        snapshot_date = date.fromisoformat(str(preview["snapshot_date"]))
        fills = tuple(
            Fill(
                str(item["instrument_id"]),
                date.fromisoformat(str(item["entry_date"])),
                FillSide.BUY,
                Quantity(int(str(item["units"]))),
                Money(Decimal(str(item["unit_cost"]))),
                Money(Decimal(0)),
                datetime.combine(snapshot_date, time(15, 30), tzinfo=ZoneInfo("Asia/Kolkata")),
                import_id,
            )
            for item in cast(list[dict[str, object]], preview["resolved_holdings"])
        )
        accounts = {item["account_id"] for item in self.ledger.accounts()}
        if account_id not in accounts:
            self.ledger.open_account(account_id, opening_cash)
        try:
            version = self.ledger.record_fills(account_id, f"legacy-import:{import_id}", 0, fills)
        except DomainValidationError as exc:
            if account_id in accounts:
                raise DomainValidationError(
                    "target account already exists and was not created by this import"
                ) from exc
            raise
        artifact_id = import_id
        if not self.publisher.catalog.has(artifact_id):
            self.publisher.publish_json(
                "imports/legacy_portfolio",
                artifact_id,
                {
                    "import_id": import_id,
                    "account_id": account_id,
                    **preview,
                    "source_path": Path(str(payload["legacy_path"])).name,
                },
                quality=QualityStatus.PARTIAL,
            )
        timestamp = datetime.now(UTC).isoformat()
        with sqlite_connection(self.database) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO legacy_portfolio_imports
                   (import_id, account_id, source_digest, snapshot_date, artifact_id,
                    resulting_ledger_version, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    account_id,
                    preview["source_digest"],
                    preview["snapshot_date"],
                    artifact_id,
                    version,
                    timestamp,
                ),
            )
        return {
            "import_id": import_id,
            "status": "IMPORTED",
            "account_id": account_id,
            "artifact_id": artifact_id,
            "resulting_ledger_version": version,
        }
