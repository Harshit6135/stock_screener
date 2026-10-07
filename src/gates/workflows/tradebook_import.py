"""Review uploaded history and apply only matching currently open holdings."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.domains.portfolio_accounting.tradebook import (
    canonical_symbol,
    parse_tradebook,
    resolve_tradebook,
)
from src.gates.workflows.tradebook_corporate_actions import TradebookCorporateActions
from src.gates.workflows.tradebook_history import apply_history, history_review
from src.platform_kernel import DomainValidationError
from src.platform_kernel.sqlite import sqlite_connection


class TradebookImport:
    def __init__(self, database, ledger, market, corporate_actions=None):
        self.database, self.ledger, self.market = str(database), ledger, market
        self.corporate_actions = TradebookCorporateActions(database, market, corporate_actions)

    def preview(self, account_id: str, raw: bytes, mode: str = "open_lots") -> dict:
        if mode not in {"open_lots", "history"}:
            raise DomainValidationError("choose full history or open-lot reconciliation")
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        parsed = parse_tradebook(raw, as_of=today, allow_unresolved=True)
        if any(trade["date"] > today for trade in parsed["trades"]):
            raise DomainValidationError("tradebook contains future-dated trades")
        actions, warnings = self.corporate_actions.resolve(parsed["trades"], today)
        parsed = parse_tradebook(raw, corporate_actions=actions, as_of=today, allow_unresolved=True)
        parsed["corporate_action_warnings"] = warnings
        upload_id = hashlib.sha256(raw).hexdigest()
        return self._save_preview(account_id, upload_id, parsed, mode)

    def refresh_preview(self, account_id, upload_id, mode="open_lots"):
        """Refresh archived trades for review without applying any ledger events."""
        if mode not in {"open_lots", "history"} or not isinstance(upload_id, str):
            raise DomainValidationError("tradebook preview request is invalid")
        with sqlite_connection(self.database, read_only=True) as connection:
            row = connection.execute(
                "SELECT parsed_json FROM tradebook_uploads WHERE account_id=? AND upload_id=?",
                (account_id, upload_id),
            ).fetchone()
        if row is None:
            raise DomainValidationError("upload this tradebook for the selected account first")
        parsed = json.loads(row[0])
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        actions, warnings = self.corporate_actions.resolve(parsed["trades"], today)
        parsed = resolve_tradebook(
            parsed, corporate_actions=actions, as_of=today, allow_unresolved=True
        )
        parsed["corporate_action_warnings"] = warnings
        return self._save_preview(account_id, upload_id, parsed, mode)

    def _save_preview(self, account_id, upload_id, parsed, mode):
        result = (
            history_review(self, account_id, upload_id, parsed)[0]
            if mode == "history"
            else self._review(account_id, upload_id, parsed)
        )
        result["corporate_action_warnings"] = parsed.get("corporate_action_warnings", [])
        with sqlite_connection(self.database) as connection:
            connection.execute(
                "INSERT INTO tradebook_uploads VALUES (?,?,?,?) ON CONFLICT(account_id,upload_id) DO UPDATE SET parsed_json=excluded.parsed_json",
                (
                    account_id,
                    upload_id,
                    json.dumps(parsed),
                    datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                ),
            )
        return result

    def _review(self, account_id, upload_id, parsed):
        projection = self.ledger.projection(account_id)
        account = next(row for row in self.ledger.accounts() if row["account_id"] == account_id)
        local = {}
        for lot in projection.open_lots:
            local[lot.instrument_id] = local.get(lot.instrument_id, 0) + lot.remaining_units.units
        holdings, matched = [], set()
        for instrument_id, units in local.items():
            identity = self.market.instrument_by_id(instrument_id)
            if not identity:
                continue
            problems = [
                group
                for group in parsed.get("unresolved_groups", [])
                if group["isin"] == identity["isin"]
                or group["symbol"] == canonical_symbol(identity["symbol"])
            ]
            if problems:
                holdings.append(
                    {
                        "instrument_id": instrument_id,
                        "symbol": identity["symbol"],
                        "portfolio_units": units,
                        "csv_units": None,
                        "eligible": False,
                        "reason": problems[0]["reason"],
                        "lots": [],
                    }
                )
                continue
            candidates = [
                group
                for group in parsed["open_groups"]
                if (group["isin"] and group["isin"] == identity["isin"])
                or (not group["isin"] and group["symbol"] == canonical_symbol(identity["symbol"]))
            ]
            group = candidates[0] if len(candidates) == 1 else None
            if group is None:
                holdings.append(
                    {
                        "instrument_id": instrument_id,
                        "symbol": identity["symbol"],
                        "portfolio_units": units,
                        "csv_units": 0,
                        "eligible": False,
                        "reason": "No unambiguous remaining buy lots in this CSV",
                        "lots": [],
                    }
                )
                continue
            matched.add(id(group))
            old_cost = sum(
                (
                    lot.unit_cost.amount * lot.remaining_units.units
                    for lot in projection.open_lots
                    if lot.instrument_id == instrument_id
                ),
                Decimal(0),
            )
            new_cost = sum(
                (Decimal(lot["unit_cost"]) * lot["units"] for lot in group["lots"]), Decimal(0)
            )
            holdings.append(
                {
                    "instrument_id": instrument_id,
                    "symbol": identity["symbol"],
                    "portfolio_units": units,
                    "csv_units": group["units"],
                    "eligible": group["units"] == units,
                    "reason": (
                        "Ready"
                        if group["units"] == units
                        else "Quantity differs: upload full history or check corporate actions"
                    ),
                    "lots": group["lots"],
                    "cash_adjustment": str(old_cost - new_cost),
                }
            )
        return {
            "account_id": account_id,
            "upload_id": upload_id,
            "expected_version": account["version"],
            "holdings": holdings,
            "trade_count": len(parsed["trades"]),
            "closed_symbols": parsed["closed_symbols"],
            "ignored_open_symbols": sum(
                id(group) not in matched for group in parsed["open_groups"]
            ),
            "duplicate_rows": parsed["duplicate_rows"],
            "skipped_rows": parsed["skipped_rows"],
            "unresolved_symbols": parsed.get("unresolved_groups", []),
            "corporate_action_adjustments": parsed.get("corporate_action_adjustments", []),
        }

    def apply(self, account_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict) or set(payload) - {"mode"} != {
            "upload_id",
            "expected_version",
            "selected_instrument_ids",
        }:
            raise DomainValidationError("tradebook apply payload is invalid")
        ids = payload["selected_instrument_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(key, str) for key in ids)
            or len(set(ids)) != len(ids)
        ):
            raise DomainValidationError("select at least one matching open holding")
        if (
            isinstance(payload["expected_version"], bool)
            or not isinstance(payload["expected_version"], int)
            or not isinstance(payload["upload_id"], str)
        ):
            raise DomainValidationError("tradebook apply payload is invalid")
        with sqlite_connection(self.database, read_only=True) as connection:
            row = connection.execute(
                "SELECT parsed_json FROM tradebook_uploads WHERE account_id=? AND upload_id=?",
                (account_id, payload["upload_id"]),
            ).fetchone()
        if row is None:
            raise DomainValidationError("upload this tradebook for the selected account first")
        parsed = json.loads(row[0])
        if any(
            not action.get("event_id") for action in parsed.get("corporate_action_adjustments", [])
        ):
            raise DomainValidationError(
                "preview this tradebook again to resolve corporate actions from exchange records"
            )
        mode = payload.get("mode", "open_lots")
        if mode == "history":
            return apply_history(self, account_id, payload, parsed)
        if mode != "open_lots":
            raise DomainValidationError("tradebook import mode is invalid")
        review = self._review(account_id, payload["upload_id"], parsed)
        eligible = {item["instrument_id"]: item for item in review["holdings"] if item["eligible"]}
        if any(key not in eligible for key in ids):
            raise DomainValidationError(
                "selected holdings must have CSV quantities matching the open portfolio"
            )
        return self.ledger.reconcile_open_lots(
            account_id,
            payload["upload_id"],
            payload["expected_version"],
            [{"instrument_id": key, "lots": eligible[key]["lots"]} for key in ids],
        )
