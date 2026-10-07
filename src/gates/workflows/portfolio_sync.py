"""Account-scoped broker balance imports and explicit trade reconciliation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.portfolio_accounting import Fill, FillSide, OpeningPosition
from src.domains.reference_data import TrackedInstrument
from src.domains.strategies.api import RETAINED_STRATEGIES
from src.platform_kernel import DomainValidationError, Money, Quantity
from src.platform_kernel.sqlite import migrate_sqlite, sqlite_connection


class BrokerClient(Protocol):
    def holdings(self) -> list[dict[str, object]]: ...
    def positions(self) -> dict[str, object]: ...


class AccountGateway(Protocol):
    def get_credentials(self, broker_account_id: str) -> dict[str, str]: ...
    def get_portfolio(self, broker_account_id: str, strategy_id: str) -> str: ...
    def validate(self, broker_account_id: str) -> object: ...
    def client(self, broker_account_id: str) -> BrokerClient: ...


class LedgerGateway(Protocol):
    def import_opening_positions(
        self,
        account_id,
        idempotency_key,
        expected_version,
        positions,
        *,
        transaction_connection=None,
    ): ...
    def accounts(self) -> list[dict[str, object]]: ...
    def projection(self, account_id: str): ...
    def fund_broker_imports(
        self, account_id: str, broker_account_id: str, *, transaction_connection=None
    ): ...
    def record_fills(self, account_id, idempotency_key, expected_version, fills) -> int: ...


class InstrumentReader(Protocol):
    def instrument_by_id(self, instrument_id: str) -> dict[str, object] | None: ...
    def tracked_instruments(self) -> list[dict[str, object]]: ...
    def upsert_instruments(self, records): ...


class PortfolioSync:
    def __init__(
        self,
        database: str | Path,
        accounts: AccountGateway,
        ledger: LedgerGateway,
        market: InstrumentReader | None = None,
    ) -> None:
        self.database, self.accounts, self.ledger = str(database), accounts, ledger
        self.market = market
        migrate_sqlite(
            self.database,
            "portfolio_sync",
            {
                1: (
                    """CREATE TABLE IF NOT EXISTS portfolio_setups (
                broker_account_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
                completed_at TEXT NOT NULL, command_checksum TEXT, result_json TEXT, PRIMARY KEY(broker_account_id, strategy_id))""",
                    """CREATE TABLE IF NOT EXISTS reconciliation_discrepancies (
                discrepancy_id INTEGER PRIMARY KEY, broker_account_id TEXT NOT NULL,
                strategy_id TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, reviewed_at TEXT)""",
                ),
                2: (
                    """CREATE TABLE IF NOT EXISTS broker_holding_imports (
                        account_id TEXT PRIMARY KEY, imported_at TEXT NOT NULL,
                        snapshot_json TEXT NOT NULL)""",
                ),
            },
        )

    def preview_holdings(self, account_id: str) -> dict[str, object]:
        """Read delivery balances for review without importing ledger positions."""
        if self.market is None:
            raise DomainValidationError("broker holding resolution is unavailable")
        self.accounts.validate(account_id)
        client = self.accounts.client(account_id)
        try:
            holdings, net = client.holdings(), client.positions()["net"]
        except Exception as exc:
            raise DomainValidationError("selected broker portfolio read failed") from exc
        observed = datetime.now(ZoneInfo("Asia/Kolkata"))
        identities = self.market.tracked_instruments()
        by_isin = {str(item["isin"]): item for item in identities}
        by_token = {str(item["provider_token"]): item for item in identities}
        resolved = {}
        unsupported = {}
        for row in holdings:
            if row.get("product") != "CNC":
                continue
            if row.get("discrepancy") or (row.get("mtf") or {}).get("quantity", 0):
                raise DomainValidationError(
                    "disputed or financed holdings require manual reconciliation"
                )
            units = int(row["quantity"]) + int(row.get("t1_quantity", 0))
            if units <= 0:
                continue
            isin = str(row["isin"])
            identity = by_isin.get(isin)
            if identity is None:
                if row["exchange"] != "NSE":
                    unsupported[str(row["instrument_token"])] = {
                        "instrument_id": f"unsupported:{row['exchange']}:{isin}",
                        "isin": isin,
                        "symbol": str(row["tradingsymbol"]),
                        "broker_symbol": str(row["tradingsymbol"]),
                        "broker_exchange": row["exchange"],
                        "units": units,
                        "unit_cost": str(row["average_price"]),
                        "price": str(row["last_price"]),
                        "purchase_date_known": False,
                        "eligible": False,
                        "imported": False,
                        "reason": "No matching NSE reference identity; excluded from balance import",
                    }
                    continue
                identity = {
                    "instrument_id": str(uuid5(NAMESPACE_URL, f"kite-holding:NSE:{isin}")),
                    "isin": isin,
                    "symbol": str(row["tradingsymbol"]),
                    "exchange": "NSE",
                    "provider_token": str(row["instrument_token"]),
                }
            key = str(identity["instrument_id"])
            if row["exchange"] == "NSE":
                identity = {**identity, "provider_token": str(row["instrument_token"])}
            if key in resolved:
                raise DomainValidationError("duplicate broker holding identity")
            resolved[key] = {
                **identity,
                "units": units,
                "unit_cost": str(row["average_price"]),
                "price": str(row["last_price"]),
                "broker_exchange": row["exchange"],
                "broker_symbol": row["tradingsymbol"],
                "purchase_date_known": False,
            }
            by_token[str(row["instrument_token"])] = identity
        for row in net:
            if row.get("product") != "CNC" or not int(row["quantity"]):
                continue
            if str(row["instrument_token"]) in unsupported:
                unsupported[str(row["instrument_token"])]["units"] += int(row["quantity"])
                continue
            if int(row.get("overnight_quantity", 0)):
                raise DomainValidationError(
                    "overnight broker positions require manual reconciliation"
                )
            identity = by_token.get(str(row["instrument_token"]))
            if identity is None:
                raise DomainValidationError(f"unresolved broker position {row['tradingsymbol']}")
            key = str(identity["instrument_id"])
            units = int(row["quantity"])
            existing = resolved.get(key)
            if existing:
                previous_units = existing["units"]
                new_units = previous_units + units
                if new_units < 0:
                    raise DomainValidationError("broker sale exceeds holding balance")
                if new_units == 0:
                    del resolved[key]
                    continue
                if units > 0:
                    existing["unit_cost"] = str(
                        (
                            Decimal(existing["unit_cost"]) * previous_units
                            + Decimal(str(row["average_price"])) * units
                        )
                        / new_units
                    )
                existing["units"] = new_units
                existing["price"] = str(row["last_price"])
            elif units > 0:
                resolved[key] = {
                    **identity,
                    "units": units,
                    "unit_cost": str(row["average_price"]),
                    "price": str(row["last_price"]),
                    "broker_exchange": row["exchange"],
                    "broker_symbol": row["tradingsymbol"],
                    "purchase_date_known": True,
                }
            else:
                raise DomainValidationError("broker sale has no matching holding")
        for row in resolved.values():
            if Decimal(row["unit_cost"]) <= 0 or not Decimal(row["unit_cost"]).is_finite():
                raise DomainValidationError("broker holding cost is unavailable")
            if Decimal(row["price"]) <= 0 or not Decimal(row["price"]).is_finite():
                raise DomainValidationError("broker holding price is unavailable")
        saved = self.holding_snapshot(account_id)
        selected_ids = {row["instrument_id"] for row in saved["holdings"]} if saved else set()
        with sqlite_connection(self.database, read_only=True) as connection:
            history_mode = bool(
                connection.execute(
                    "SELECT 1 FROM ledger_events WHERE account_id=? AND event_type='FILL_RECORDED' AND json_extract(event_json,'$.historical_import')=1 LIMIT 1",
                    (account_id,),
                ).fetchone()
            )
        if history_mode:
            selected_ids = {
                lot.instrument_id for lot in self.ledger.projection(account_id).open_lots
            }
        return {
            "account_id": account_id,
            "opening_date": next(
                row["opening_date"]
                for row in self.ledger.accounts()
                if row["account_id"] == account_id
            ),
            "available_cash": str(self.ledger.projection(account_id).cash.amount),
            "observed_at": observed.isoformat(),
            "import_complete": saved is not None,
            "history_mode": history_mode,
            "holdings": [{**row, "imported": key in selected_ids} for key, row in resolved.items()]
            + [row for row in unsupported.values() if row["units"] > 0],
        }

    def import_holdings(
        self,
        account_id: str,
        selected_ids: list[str] | None = None,
        purchase_dates: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Import selected balances and retain that scope on subsequent refreshes."""
        preview = self.preview_holdings(account_id)
        observed = datetime.fromisoformat(preview["observed_at"])
        available = {
            row["instrument_id"]: row for row in preview["holdings"] if row.get("eligible", True)
        }
        all_ids = {row["instrument_id"] for row in preview["holdings"]}
        if selected_ids is not None and (
            not isinstance(selected_ids, list)
            or any(not isinstance(key, str) for key in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)
        ):
            raise DomainValidationError(
                "selected_instrument_ids must be a list of unique identities"
            )
        dates = {}
        if purchase_dates is not None:
            if not isinstance(purchase_dates, dict) or not set(purchase_dates) <= set(
                selected_ids or []
            ):
                raise DomainValidationError("purchase dates must belong to selected holdings")
            for key, value in purchase_dates.items():
                try:
                    day = date.fromisoformat(value)
                    if (
                        day.isoformat() != value
                        or not preview["opening_date"] <= value <= observed.date().isoformat()
                    ):
                        raise ValueError
                except (TypeError, ValueError) as exc:
                    raise DomainValidationError(
                        "purchase dates must be valid dates between account opening and today"
                    ) from exc
                dates[key] = day
        if preview.get("history_mode"):
            projection = self.ledger.projection(account_id)
            local_units = {}
            for lot in projection.open_lots:
                local_units[lot.instrument_id] = (
                    local_units.get(lot.instrument_id, 0) + lot.remaining_units.units
                )
            if selected_ids is not None and not set(selected_ids) <= set(available):
                raise DomainValidationError(
                    "selected holding no longer exists at the broker; reload preview"
                )
            new_ids = set(selected_ids or []) - set(local_units)
            if purchase_dates is not None and set(dates) != new_ids:
                raise DomainValidationError(
                    "enter a purchase date for every newly selected holding"
                )
            saved = self.holding_snapshot(account_id)
            previous_rows = (
                {row["instrument_id"]: row for row in saved["holdings"]} if saved else {}
            )
            rows = [
                {
                    **row,
                    "purchase_date_known": (
                        previous_rows.get(key, {}).get("purchase_date_known", True)
                        if key in local_units
                        else (key in dates or row["purchase_date_known"])
                    ),
                }
                for key, row in available.items()
                if key in local_units or key in new_ids
            ]
            self.market.upsert_instruments(
                [
                    TrackedInstrument(
                        row["instrument_id"],
                        row["isin"],
                        row["symbol"],
                        "NSE",
                        row["provider_token"],
                        observed.date(),
                    )
                    for row in rows
                ]
            )
            snapshot = {
                "observed_at": observed.isoformat(),
                "holdings": rows,
                "ignored_instrument_ids": sorted(all_ids - set(local_units) - new_ids),
            }
            with sqlite_connection(self.database, row_factory=True) as connection:
                connection.execute("BEGIN IMMEDIATE")
                account = connection.execute(
                    "SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)
                ).fetchone()
                if account is None:
                    raise DomainValidationError("local portfolio account not found")
                current_units = {}
                for lot in self.ledger.projection(account_id).open_lots:
                    current_units[lot.instrument_id] = (
                        current_units.get(lot.instrument_id, 0) + lot.remaining_units.units
                    )
                if current_units != local_units:
                    raise DomainValidationError("portfolio changed during import; reload preview")
                version = connection.execute(
                    "SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0]
                if new_ids:
                    positions = [
                        OpeningPosition(
                            key,
                            dates.get(key, observed.date()),
                            Quantity(available[key]["units"]),
                            Money(Decimal(available[key]["unit_cost"])),
                            observed,
                            json.dumps(
                                {
                                    "source": "kite-opening-balance",
                                    "broker_account_id": account_id,
                                    "purchase_date_known": key in dates
                                    or available[key]["purchase_date_known"],
                                    "purchase_date_source": (
                                        "user"
                                        if key in dates
                                        else (
                                            "broker-current-day"
                                            if available[key]["purchase_date_known"]
                                            else "unknown"
                                        )
                                    ),
                                    "history_incomplete": True,
                                }
                            ),
                        )
                        for key in sorted(new_ids)
                    ]
                    self.ledger.import_opening_positions(
                        account_id,
                        f"kite-missing-holdings:{version}:"
                        + hashlib.sha256(json.dumps(positions, default=str).encode()).hexdigest(),
                        version,
                        positions,
                        transaction_connection=connection,
                    )
                funding = self.ledger.fund_broker_imports(
                    account_id, account_id, transaction_connection=connection
                )
                version = funding["version"]
                connection.execute(
                    "INSERT INTO broker_holding_imports VALUES (?,?,?) ON CONFLICT(account_id) DO UPDATE SET snapshot_json=excluded.snapshot_json",
                    (account_id, observed.isoformat(), json.dumps(snapshot)),
                )
            return {
                "account_id": account_id,
                "imported_positions": len(new_ids),
                "holding_count": len(rows),
                "version": version,
                "ignored_count": len(all_ids) - len(rows),
                "cash_deducted": funding["cash_deducted"],
                "cash_imported": False,
                "basis": "broker_opening_balance" if new_ids else "tradebook_price_refresh",
                "quantity_mismatches": [
                    row["symbol"]
                    for key, row in available.items()
                    if key in local_units and row["units"] != local_units[key]
                ],
            }
        saved = self.holding_snapshot(account_id)
        previous_ids = {row["instrument_id"] for row in saved["holdings"]} if saved else set()
        if selected_ids is None:
            if saved is None:
                raise DomainValidationError("select holdings in the import preview first")
            selection = previous_ids
        else:
            if (
                not isinstance(selected_ids, list)
                or any(not isinstance(key, str) for key in selected_ids)
                or len(set(selected_ids)) != len(selected_ids)
            ):
                raise DomainValidationError(
                    "selected_instrument_ids must be a list of unique identities"
                )
            selection = set(selected_ids)
            if not previous_ids.issubset(selection):
                raise DomainValidationError(
                    "already imported holdings cannot be removed from ledger history; reconcile trades instead"
                )
        if not selection.issubset(available):
            raise DomainValidationError(
                "selected holding no longer exists at the broker; reload or reconcile trades"
            )
        resolved = {key: row for key, row in available.items() if key in selection}
        if saved:
            for row in saved["holdings"]:
                if row["instrument_id"] in resolved:
                    resolved[row["instrument_id"]]["purchase_date_known"] = row[
                        "purchase_date_known"
                    ]
        identities = self.market.tracked_instruments()
        # Reference identities may include ETFs and bonds outside the research universe.
        self.market.upsert_instruments(
            [
                TrackedInstrument(
                    row["instrument_id"],
                    row["isin"],
                    row["symbol"],
                    "NSE",
                    row["provider_token"],
                    observed.date(),
                )
                for row in resolved.values()
                if row["instrument_id"] not in {item["instrument_id"] for item in identities}
            ]
        )
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            account = connection.execute(
                "SELECT 1 FROM ledger_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if not account:
                raise DomainValidationError("local portfolio account not found")
            imported = connection.execute(
                "SELECT snapshot_json FROM broker_holding_imports WHERE account_id=?", (account_id,)
            ).fetchone()
            version = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
            count = 0
            if imported:
                persisted_ids = {
                    row["instrument_id"] for row in json.loads(imported[0])["holdings"]
                }
                if persisted_ids != previous_ids:
                    raise DomainValidationError(
                        "import selection changed concurrently; reload preview"
                    )
                projection = self.ledger.projection(account_id)
                local = {}
                for lot in projection.open_lots:
                    local[lot.instrument_id] = (
                        local.get(lot.instrument_id, 0) + lot.remaining_units.units
                    )
                if local != {
                    key: row["units"] for key, row in resolved.items() if key in previous_ids
                }:
                    raise DomainValidationError(
                        "broker quantities differ from the imported ledger; reconcile trades before refreshing"
                    )
            else:
                if connection.execute(
                    "SELECT 1 FROM ledger_events WHERE account_id=? AND event_type IN ('FILL_RECORDED','OPENING_POSITION_IMPORTED')",
                    (account_id,),
                ).fetchone():
                    raise DomainValidationError(
                        "existing portfolio trades require reconciliation before importing"
                    )
            new_rows = {key: row for key, row in resolved.items() if key not in previous_ids}
            if purchase_dates is not None and set(dates) != set(new_rows):
                raise DomainValidationError(
                    "enter a purchase date for every newly selected holding"
                )
            for key in dates:
                resolved[key]["purchase_date_known"] = True
            if new_rows:
                positions = [
                    OpeningPosition(
                        key,
                        dates.get(key, observed.date()),
                        Quantity(row["units"]),
                        Money(Decimal(row["unit_cost"])),
                        observed,
                        json.dumps(
                            {
                                "source": "kite-opening-balance",
                                "broker_account_id": account_id,
                                "purchase_date_known": row["purchase_date_known"],
                                "purchase_date_source": (
                                    "user"
                                    if key in dates
                                    else (
                                        "broker-current-day"
                                        if row["purchase_date_known"]
                                        else "unknown"
                                    )
                                ),
                                "broker_symbol": row["broker_symbol"],
                                "broker_exchange": row["broker_exchange"],
                            },
                            sort_keys=True,
                        ),
                    )
                    for key, row in new_rows.items()
                ]
                if positions:
                    version = self.ledger.import_opening_positions(
                        account_id,
                        f"kite-import:{account_id}:{version}",
                        version,
                        positions,
                        transaction_connection=connection,
                    )
                    count = len(positions)
            funding = self.ledger.fund_broker_imports(
                account_id, account_id, transaction_connection=connection
            )
            version = funding["version"]
            snapshot = {
                "observed_at": observed.isoformat(),
                "holdings": list(resolved.values()),
                "ignored_instrument_ids": sorted(all_ids - selection),
            }
            connection.execute(
                "INSERT INTO broker_holding_imports VALUES (?,?,?) ON CONFLICT(account_id) DO UPDATE SET snapshot_json=excluded.snapshot_json",
                (account_id, observed.isoformat(), json.dumps(snapshot)),
            )
        return {
            "account_id": account_id,
            "imported_positions": count,
            "holding_count": len(resolved),
            "version": version,
            "ignored_count": len(all_ids) - len(resolved),
            "cash_deducted": funding["cash_deducted"],
            "cash_imported": False,
            "basis": "broker_opening_balance",
        }

    def holding_snapshot(self, account_id: str) -> dict[str, object] | None:
        with sqlite_connection(self.database, read_only=True) as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM broker_holding_imports WHERE account_id=?", (account_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def setup(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {
            "broker_account_id",
            "strategy_id",
            "opening_cash",
            "positions",
            "idempotency_key",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or not isinstance(payload["positions"], list)
        ):
            raise DomainValidationError("portfolio setup payload is invalid")
        broker_id, strategy_id = str(payload["broker_account_id"]), str(payload["strategy_id"])
        if (
            strategy_id not in RETAINED_STRATEGIES
            or not isinstance(payload["idempotency_key"], str)
            or not payload["idempotency_key"].strip()
        ):
            raise DomainValidationError("setup strategy or idempotency key is invalid")
        self.accounts.get_credentials(broker_id)
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with sqlite_connection(self.database, read_only=True, row_factory=True) as connection:
            existing = connection.execute(
                "SELECT * FROM portfolio_setups WHERE broker_account_id=? AND strategy_id=?",
                (broker_id, strategy_id),
            ).fetchone()
        if existing:
            if existing["command_checksum"] == checksum and existing["result_json"]:
                return json.loads(existing["result_json"])
            raise DomainValidationError("day-zero setup is already complete; use reconciliation")
        try:
            cash = Money(Decimal(str(payload["opening_cash"])))
        except Exception as exc:
            raise DomainValidationError("opening_cash is invalid") from exc
        if cash.amount < 0:
            raise DomainValidationError("opening_cash must be non-negative")
        positions: list[OpeningPosition] = []
        imported_at = datetime.now(UTC)
        selected = set()
        broker_holdings = {}
        if payload["positions"]:
            if self.market is None:
                raise DomainValidationError("broker holding resolution is unavailable")
            self.accounts.validate(broker_id)
            try:
                broker_holdings = {
                    str(row["isin"]): row for row in self.accounts.client(broker_id).holdings()
                }
            except Exception as exc:
                raise DomainValidationError("broker holdings verification failed") from exc
        for row in payload["positions"]:
            if not isinstance(row, dict) or set(row) != {
                "instrument_id",
                "units",
                "unit_cost",
                "acquisition_date",
                "provenance",
            }:
                raise DomainValidationError("opening position is invalid")
            if (
                isinstance(row["units"], bool)
                or not isinstance(row["units"], int)
                or row["units"] < 1
                or row["instrument_id"] in selected
            ):
                raise DomainValidationError(
                    "opening quantity must be positive, integral and unique"
                )
            selected.add(row["instrument_id"])
            identity = self.market.instrument_by_id(str(row["instrument_id"]))
            holding = broker_holdings.get(str(identity["isin"])) if identity else None
            if not holding or int(holding["quantity"]) != row["units"]:
                raise DomainValidationError(
                    "import must use the entire selected broker holding quantity"
                )
            acquired = date.fromisoformat(str(row["acquisition_date"]))
            if acquired > imported_at.date() or not str(row["provenance"]).strip():
                raise DomainValidationError("opening acquisition date or provenance is invalid")
            positions.append(
                OpeningPosition(
                    str(row["instrument_id"]),
                    date.fromisoformat(str(row["acquisition_date"])),
                    Quantity(int(row["units"])),
                    Money(Decimal(str(row["unit_cost"]))),
                    imported_at,
                    str(row["provenance"]),
                )
            )
        with sqlite_connection(self.database, row_factory=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM portfolio_setups WHERE broker_account_id=? AND strategy_id=?",
                (broker_id, strategy_id),
            ).fetchone():
                raise DomainValidationError(
                    "day-zero setup was completed concurrently; reload setup status"
                )
            binding = connection.execute(
                "SELECT ledger_account_id FROM strategy_portfolios WHERE broker_account_id=? AND strategy_id=?",
                (broker_id, strategy_id),
            ).fetchone()
            ledger_id = binding[0] if binding else f"{broker_id}:{strategy_id}"
            connection.execute(
                "INSERT OR IGNORE INTO ledger_accounts(account_id,opening_cash,currency) VALUES (?,?,?)",
                (ledger_id, str(cash.amount), cash.currency),
            )
            account = connection.execute(
                "SELECT opening_cash FROM ledger_accounts WHERE account_id=?", (ledger_id,)
            ).fetchone()
            if Decimal(account[0]) != cash.amount:
                raise DomainValidationError("existing ledger opening cash differs from setup")
            connection.execute(
                "INSERT OR IGNORE INTO strategy_portfolios VALUES (?,?,?,?)",
                (broker_id, strategy_id, ledger_id, imported_at.isoformat()),
            )
            version = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?",
                (ledger_id,),
            ).fetchone()[0]
            if version:
                raise DomainValidationError("day-zero setup requires an unused ledger")
            if positions:
                version = self.ledger.import_opening_positions(
                    ledger_id,
                    payload["idempotency_key"],
                    version,
                    positions,
                    transaction_connection=connection,
                )
            result = {
                "broker_account_id": broker_id,
                "strategy_id": strategy_id,
                "ledger_account_id": ledger_id,
                "version": version,
                "imported_positions": len(positions),
            }
            connection.execute(
                "INSERT INTO portfolio_setups(broker_account_id,strategy_id,completed_at,command_checksum,result_json) VALUES (?,?,?,?,?)",
                (broker_id, strategy_id, imported_at.isoformat(), checksum, json.dumps(result)),
            )
            return result

    def reconcile(self, payload: dict[str, Any]) -> dict[str, object]:
        required = {"broker_account_id", "strategy_id", "trades", "idempotency_key"}
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or not isinstance(payload["trades"], list)
        ):
            raise DomainValidationError("portfolio reconciliation payload is invalid")
        ledger_id = self.accounts.get_portfolio(
            str(payload["broker_account_id"]), str(payload["strategy_id"])
        )
        version = next(
            item["version"] for item in self.ledger.accounts() if item["account_id"] == ledger_id
        )
        fills: list[Fill] = []
        for row in payload["trades"]:
            if not isinstance(row, dict) or set(row) != {
                "trade_id",
                "instrument_id",
                "side",
                "units",
                "price",
                "executed_at",
            }:
                raise DomainValidationError("reconciliation trade is invalid")
            at = datetime.fromisoformat(str(row["executed_at"]))
            if at.tzinfo is None:
                raise DomainValidationError("reconciliation trade timestamp must be timezone-aware")
            fills.append(
                Fill(
                    str(row["instrument_id"]),
                    at.date(),
                    FillSide(str(row["side"])),
                    Quantity(int(row["units"])),
                    Money(Decimal(str(row["price"]))),
                    executed_at=at,
                    broker_trade_id=str(row["trade_id"]),
                )
            )
        if not fills:
            return {"ledger_account_id": ledger_id, "version": version, "posted_fills": 0}
        version = self.ledger.record_fills(
            ledger_id, str(payload["idempotency_key"]), int(version), fills
        )
        return {"ledger_account_id": ledger_id, "version": version, "posted_fills": len(fills)}
