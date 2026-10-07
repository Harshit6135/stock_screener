"""Atomically append historical fills and verified splits without inventing cash."""

import hashlib
import json
from datetime import date

from src.domains.portfolio_accounting.api import Fill, StockSplit, project
from src.platform_kernel import DomainValidationError, Money


def import_history(ledger, account_id, import_id, expected_version, events):
    serialized = []
    for event in events:
        if isinstance(event, Fill):
            serialized.append(("FILL_RECORDED", ledger._fill_event(event), event.executed_at))
        elif isinstance(event, StockSplit):
            serialized.append(
                (
                    "STOCK_SPLIT_APPLIED",
                    {
                        "instrument_id": event.instrument_id,
                        "effective_at": event.effective_at.isoformat(),
                        "numerator": event.numerator,
                        "denominator": event.denominator,
                        "source_url": event.source_url,
                        **(
                            {"action_type": event.action_type}
                            if event.action_type != "SPLIT"
                            else {}
                        ),
                    },
                    event.effective_at,
                )
            )
        else:
            raise DomainValidationError("unsupported historical event")
    serialized.sort(key=lambda row: (row[2], row[0] != "STOCK_SPLIT_APPLIED"))
    command_json = json.dumps([(kind, payload) for kind, payload, _ in serialized], sort_keys=True)
    checksum = hashlib.sha256(command_json.encode()).hexdigest()
    key = "tradebook-history:" + import_id
    with ledger._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        prior_command = connection.execute(
            "SELECT payload_checksum,command_json,resulting_version FROM ledger_commands WHERE account_id=? AND idempotency_key=?",
            (account_id, key),
        ).fetchone()
        if prior_command:
            if prior_command["payload_checksum"] != checksum:
                raise DomainValidationError("tradebook import conflicts with previous application")
            return json.loads(prior_command["command_json"])
        account = connection.execute(
            "SELECT * FROM ledger_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if account is None:
            raise DomainValidationError("account does not exist")
        rows = connection.execute(
            "SELECT * FROM ledger_events WHERE account_id=? ORDER BY version", (account_id,)
        ).fetchall()
        current = rows[-1]["version"] if rows else 0
        if current != expected_version:
            raise DomainValidationError("stale ledger version")
        if any(
            row["event_type"] not in {"FILL_RECORDED", "STOCK_SPLIT_APPLIED", "CASH_TRANSFER"}
            for row in rows
        ):
            raise DomainValidationError(
                "full history requires an account without opening-position imports; create a fresh portfolio"
            )
        previous = []
        seen = {}
        transfers = 0
        for row in rows:
            payload = json.loads(row["event_json"])
            if row["event_type"] == "CASH_TRANSFER":
                transfers += Money(payload["amount"]).amount * (
                    1 if payload["direction"] == "DEPOSIT" else -1
                )
                continue
            parsed = ledger._parse_accounting_event(payload, row["event_type"])
            previous.append(parsed)
            identity = (
                payload.get("broker_trade_id")
                if row["event_type"] == "FILL_RECORDED"
                else payload.get("action_type", "SPLIT").lower()
                + ":"
                + payload["instrument_id"]
                + ":"
                + payload["effective_at"]
            )
            if identity:
                seen[identity] = payload
        additions, skipped = [], 0
        for kind, payload, at in serialized:
            identity = (
                payload.get("broker_trade_id")
                if kind == "FILL_RECORDED"
                else payload.get("action_type", "SPLIT").lower()
                + ":"
                + payload["instrument_id"]
                + ":"
                + payload["effective_at"]
            )
            if identity in seen:
                if seen[identity] != payload:
                    raise DomainValidationError(
                        "a previously imported trade has changed; review the source export"
                    )
                skipped += kind == "FILL_RECORDED"
                continue
            if at.date() < date.fromisoformat(account["opening_date"]):
                raise DomainValidationError(
                    "tradebook contains trades before the account opening date"
                )
            if previous:
                last = (
                    previous[-1].executed_at
                    if isinstance(previous[-1], Fill)
                    else previous[-1].effective_at
                )
                if at < last:
                    raise DomainValidationError(
                        "new historical trades precede existing ledger history; upload complete history to a fresh account"
                    )
            seen[identity] = payload
            parsed = ledger._parse_accounting_event(payload, kind)
            previous.append(parsed)
            additions.append((kind, payload, at))
        if not serialized:
            raise DomainValidationError("select at least one symbol to import")
        projection = project(
            Money(Money(account["opening_cash"]).amount + transfers, account["currency"]), previous
        )
        for kind, payload, at in additions:
            current += 1
            connection.execute(
                "INSERT INTO ledger_events(account_id,version,event_type,event_json,occurred_at) VALUES (?,?,?,?,?)",
                (account_id, current, kind, json.dumps(payload, sort_keys=True), at.isoformat()),
            )
        result = {
            "version": current,
            "imported_trades": sum(kind == "FILL_RECORDED" for kind, _, _ in additions),
            "duplicate_trades": skipped,
            "corporate_actions": sum(kind == "STOCK_SPLIT_APPLIED" for kind, _, _ in additions),
            "cash": str(projection.cash.amount),
            "realised_pnl": str(projection.realised_pnl.amount),
            "open_units": sum(lot.remaining_units.units for lot in projection.open_lots),
        }
        connection.execute(
            "INSERT INTO ledger_commands(account_id,idempotency_key,resulting_version,payload_checksum,command_json) VALUES (?,?,?,?,?)",
            (account_id, key, current, checksum, json.dumps(result, sort_keys=True)),
        )
        return result
