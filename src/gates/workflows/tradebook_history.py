"""Review and construct complete chronological equity tradebook history."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from src.domains.portfolio_accounting.api import Fill, FillSide, StockSplit, project
from src.domains.portfolio_accounting.history_import import import_history
from src.domains.portfolio_accounting.tradebook import canonical_symbol
from src.domains.reference_data import TrackedInstrument
from src.platform_kernel import DomainValidationError, Money, Quantity


def history_review(importer, account_id, upload_id, parsed):
    account = next(
        (row for row in importer.ledger.accounts() if row["account_id"] == account_id), None
    )
    if account is None:
        raise DomainValidationError("account does not exist")
    identities = importer.market.tracked_instruments()
    aliases = {
        a["old_isin"]: a["new_isin"]
        for a in parsed.get("corporate_actions", [])
        if not a.get("reason") and a["old_isin"] and a["old_isin"] != a["new_isin"]
    }

    def canonical_isin(isin):
        seen = set()
        while isin in aliases and isin not in seen:
            seen.add(isin)
            isin = aliases[isin]
        return isin

    symbol_isins = {}
    for trade in parsed["trades"]:
        if trade["isin"]:
            symbol_isins.setdefault(trade["symbol"], set()).add(canonical_isin(trade["isin"]))
    groups = {}
    for trade in parsed["trades"]:
        known_isins = symbol_isins.get(trade["symbol"], set())
        key = canonical_isin(trade["isin"]) or (
            next(iter(known_isins)) if len(known_isins) == 1 else trade["symbol"]
        )
        groups.setdefault(key, []).append(trade)
    holdings, resolved = [], {}
    problems = {p["isin"] or p["symbol"]: p["reason"] for p in parsed.get("unresolved_groups", [])}
    for key, trades in groups.items():
        sample = trades[-1]
        matches = [
            row
            for row in identities
            if (sample["isin"] and canonical_isin(row["isin"]) == canonical_isin(sample["isin"]))
            or (not sample["isin"] and canonical_symbol(row["symbol"]) == sample["symbol"])
        ]
        identity = next((row for row in matches if row["exchange"] == "NSE"), None)
        if identity is None:
            identity = {
                "instrument_id": str(uuid5(NAMESPACE_URL, "tradebook:NSE:" + key)),
                "isin": canonical_isin(sample["isin"]) or "SYMBOL:" + sample["symbol"],
                "symbol": sample["symbol"],
                "exchange": "NSE",
                "provider_token": "",
            }
        instrument_id = identity["instrument_id"]
        resolved[instrument_id] = {"identity": identity, "trades": trades}
        reason = problems.get(key)
        if min(t["date"] for t in trades) < account["opening_date"]:
            reason = "Trades precede the account opening date"
        open_group = next(
            (g for g in parsed["open_groups"] if (g["isin"] or g["symbol"]) == key), None
        )
        holdings.append(
            {
                "instrument_id": instrument_id,
                "symbol": identity["symbol"],
                "eligible": reason is None,
                "reason": reason or "Ready",
                "trade_count": len(trades),
                "buy_count": sum(t["side"] == "BUY" for t in trades),
                "sell_count": sum(t["side"] == "SELL" for t in trades),
                "csv_units": open_group["units"] if open_group else 0,
                "lots": open_group["lots"] if open_group else [],
            }
        )
    existing = importer.ledger.events(account_id)
    blocked = any(
        e["event_type"] not in {"FILL_RECORDED", "STOCK_SPLIT_APPLIED", "CASH_TRANSFER", "CHARGES_RECONCILED"}
        for e in existing
    )
    summary = None
    if all(h["eligible"] for h in holdings):
        events = history_events(resolved, parsed)
        # Preview the uploaded history independently of existing executions.
        projection = project(Money(account["opening_cash"]), events)
        cash, minimum = Decimal(account["opening_cash"]), Decimal(account["opening_cash"])
        for event in events:
            if isinstance(event, Fill):
                cash += (
                    event.price.amount
                    * event.units.units
                    * (1 if event.side == FillSide.SELL else -1)
                    - event.fee.amount
                )
                minimum = min(minimum, cash)
        summary = {
            "cash": str(projection.cash.amount),
            "realised_pnl": str(projection.realised_pnl.amount),
            "minimum_cash": str(minimum),
            "initial_balance": account["opening_cash"],
            "opening_date": account["opening_date"],
        }
    return {
        "account_id": account_id,
        "upload_id": upload_id,
        "expected_version": account["version"],
        "mode": "history",
        "holdings": holdings,
        "trade_count": len(parsed["trades"]),
        "closed_symbols": parsed["closed_symbols"],
        "duplicate_rows": parsed["duplicate_rows"],
        "skipped_rows": parsed["skipped_rows"],
        "fees_provided": parsed.get("fees_provided", False),
        "corporate_action_adjustments": parsed.get("corporate_action_adjustments", []),
        "unresolved_symbols": parsed.get("unresolved_groups", []),
        "blocked_reason": (
            "Full history requires a fresh account without opening-position imports."
            if blocked
            else None
        ),
        "summary": summary,
    }, resolved


def history_events(resolved, parsed):
    events = []
    for instrument_id, group in resolved.items():
        for trade in group["trades"]:
            timestamp = datetime.fromisoformat(trade["timestamp"])
            if timestamp.utcoffset() is None:
                timestamp = timestamp.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            trade_key = (
                ":".join((trade["exchange"], trade["date"], trade["trade_id"]))
                if trade["trade_id"]
                else hashlib.sha256(json.dumps(trade, sort_keys=True).encode()).hexdigest()
            )
            events.append(
                Fill(
                    instrument_id,
                    date.fromisoformat(trade["date"]),
                    FillSide(trade["side"]),
                    Quantity(trade["units"]),
                    Money(trade["price"]),
                    Money(trade.get("fee", "0")),
                    timestamp,
                    (
                        "tradebook:fees-provided"
                        if parsed.get("fees_provided")
                        else "tradebook:charges-unavailable"
                    ),
                    "tradebook:" + trade_key,
                    True,
                )
            )
        for action in parsed.get("corporate_action_adjustments", []):
            if action["symbol"] == group["trades"][-1]["symbol"] and (
                not action.get("isin") or action["isin"] == group["identity"]["isin"]
            ):
                events.append(
                    StockSplit(
                        instrument_id,
                        datetime.fromisoformat(action["effective_date"] + "T00:00:00+05:30"),
                        action["numerator"],
                        action["denominator"],
                        action["source_url"],
                        action_type=action["action_type"],
                    )
                )
    return sorted(
        events,
        key=lambda e: (
            e.executed_at if isinstance(e, Fill) else e.effective_at,
            isinstance(e, Fill),
        ),
    )


def apply_history(importer, account_id, payload, parsed):
    review, resolved = history_review(importer, account_id, payload["upload_id"], parsed)
    if review["blocked_reason"]:
        raise DomainValidationError(review["blocked_reason"])
    selected = payload["selected_instrument_ids"]
    eligible = {h["instrument_id"] for h in review["holdings"] if h["eligible"]}
    if not set(selected) <= eligible:
        raise DomainValidationError("selected symbols contain unresolved trades or dates")
    groups = {key: resolved[key] for key in selected}
    events = history_events(groups, parsed)
    selection_hash = hashlib.sha256(json.dumps(sorted(selected)).encode()).hexdigest()[:16]
    result = import_history(
        importer.ledger,
        account_id,
        payload["upload_id"] + ":" + selection_hash,
        payload["expected_version"],
        events,
    )
    importer.market.upsert_instruments(
        [
            TrackedInstrument(
                key,
                group["identity"]["isin"],
                group["identity"]["symbol"],
                "NSE",
                group["identity"]["provider_token"],
                date.fromisoformat(max(t["date"] for t in group["trades"])),
            )
            for key, group in groups.items()
        ]
    )
    return result
