"""Parse exported equity trades and reconstruct remaining FIFO buy lots."""

import csv
import io
import re
from collections import deque
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from src.platform_kernel import DomainValidationError


def canonical_symbol(symbol: str) -> str:
    return re.sub(r"-(EQ|BE|BZ)$", "", symbol.strip().upper())


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.strip().lower())


def parse_tradebook(
    raw: bytes, *, corporate_actions=(), as_of=None, allow_unresolved=False
) -> dict:
    try:
        return _parse_tradebook(raw, corporate_actions, as_of, allow_unresolved)
    except csv.Error as exc:
        raise DomainValidationError(
            "invalid CSV structure; upload the original tradebook export"
        ) from exc


def _parse_tradebook(raw: bytes, corporate_actions, as_of, allow_unresolved) -> dict:
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise DomainValidationError("upload a non-empty tradebook CSV up to 4 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainValidationError("tradebook must be a UTF-8 CSV export") from exc
    lines = text.splitlines()
    aliases = {
        "symbol": {"symbol", "tradingsymbol"},
        "date": {"tradedate", "date"},
        "side": {"tradetype", "transactiontype", "side", "buysell"},
        "units": {"quantity", "qty", "units"},
        "price": {"price", "tradeprice", "averageprice"},
        "isin": {"isin"},
        "trade_id": {"tradeid"},
        "exchange": {"exchange"},
        "time": {"orderexecutiontime", "exchangetimestamp", "filltimestamp", "tradetime"},
        "segment": {"segment"},
        "fee": {"fee", "fees", "charges", "totalcharges", "transactioncharges"},
    }
    columns = None
    for index, line in enumerate(lines[:50]):
        names = [_header(value) for value in next(csv.reader([line]))]
        found = {
            key: next((i for i, name in enumerate(names) if name in options), None)
            for key, options in aliases.items()
        }
        if all(found[key] is not None for key in ("symbol", "date", "side", "units", "price")):
            columns, start = found, index + 1
            break
    if columns is None:
        raise DomainValidationError(
            "CSV needs symbol, trade_date, trade_type, quantity and price columns"
        )
    trades, seen, duplicates, skipped = [], {}, 0, 0
    for line_number, row in enumerate(csv.reader(io.StringIO("\n".join(lines[start:]))), start + 1):
        if not row or not any(value.strip() for value in row):
            continue

        def cell(key, row=row):
            offset = columns[key]
            return row[offset].strip() if offset is not None and offset < len(row) else ""

        if cell("segment").upper() not in {"", "EQ", "EQUITY", "CASH"}:
            skipped += 1
            continue
        try:
            symbol = canonical_symbol(cell("symbol"))
            side = cell("side").upper()
            if side not in {"BUY", "SELL"} or not symbol:
                raise ValueError
            quantity = Decimal(cell("units").replace(",", ""))
            price = Decimal(cell("price").replace(",", ""))
            fee = Decimal(cell("fee").replace(",", "") or "0")
            if (
                not quantity.is_finite()
                or quantity <= 0
                or quantity != quantity.to_integral_value()
                or not price.is_finite()
                or price <= 0
                or not fee.is_finite()
                or fee < 0
            ):
                raise ValueError
            day = None
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    day = (
                        datetime.strptime(cell("date"), fmt)
                        .replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                        .date()
                    )
                    break
                except ValueError:
                    continue
            if day is None:
                raise ValueError
            timestamp = day.isoformat() + "T00:00:00"
            if cell("time"):
                time_value = cell("time").replace(" ", "T")
                parsed = datetime.fromisoformat(
                    time_value if "T" in time_value else day.isoformat() + "T" + time_value
                )
                if parsed.date() != day:
                    raise ValueError
                timestamp = parsed.isoformat()
            trade = {
                "symbol": symbol,
                "isin": cell("isin").upper(),
                "side": side,
                "units": int(quantity),
                "price": str(price),
                "fee": str(fee),
                "date": day.isoformat(),
                "timestamp": timestamp,
                "trade_id": cell("trade_id"),
                "exchange": cell("exchange").upper(),
                "row": line_number,
            }
        except (ValueError, InvalidOperation) as exc:
            raise DomainValidationError(f"invalid equity trade on CSV row {line_number}") from exc
        if trade["trade_id"]:
            key = (trade["exchange"], trade["trade_id"], trade["date"])
            if key in seen:
                if {k: v for k, v in trade.items() if k != "row"} != {
                    k: v for k, v in seen[key].items() if k != "row"
                }:
                    raise DomainValidationError(
                        f"conflicting duplicate trade on CSV row {line_number}"
                    )
                duplicates += 1
                continue
            seen[key] = trade
        trades.append(trade)
    if not trades:
        raise DomainValidationError("CSV contains no equity trades")
    return resolve_tradebook(
        {
            "trades": trades,
            "duplicate_rows": duplicates,
            "skipped_rows": skipped,
            "fees_provided": columns["fee"] is not None,
        },
        corporate_actions=corporate_actions,
        as_of=as_of,
        allow_unresolved=allow_unresolved,
    )


def resolve_tradebook(parsed, *, corporate_actions=(), as_of=None, allow_unresolved=False):
    """Rebuild FIFO from validated trades, preserving execution IDs and CSV rows."""
    trades = parsed["trades"]
    symbol_isins = {trade["symbol"]: trade["isin"] for trade in trades if trade["isin"]}
    aliases = {
        action["old_isin"]: action["new_isin"]
        for action in corporate_actions
        if not action.get("reason")
        and action["old_isin"]
        and action["old_isin"] != action["new_isin"]
    }

    def resolved_isin(isin):
        visited = set()
        while isin in aliases and isin not in visited:
            visited.add(isin)
            isin = aliases[isin]
        return isin

    queues, groups, unresolved, adjustments = {}, {}, {}, []
    actions = sorted(corporate_actions, key=lambda action: action["effective_date"])
    action_index = 0

    def apply_actions(through):
        nonlocal action_index
        while action_index < len(actions) and actions[action_index]["effective_date"] <= through:
            action = actions[action_index]
            action_index += 1
            key = resolved_isin(action["old_isin"]) or action["symbol"]
            queue = queues.get(key) or queues.get(action["symbol"])
            if not queue:
                continue
            if key not in groups:
                key = action["symbol"]
            if action.get("reason"):
                if not allow_unresolved:
                    raise DomainValidationError(action["reason"])
                unresolved[key] = {**groups[key], "reason": action["reason"]}
                continue
            factor = Decimal(action["numerator"]) / Decimal(action["denominator"])
            if action["action_type"] not in {"SPLIT", "BONUS"} or factor <= 0:
                raise DomainValidationError("unsupported verified tradebook action")
            before = sum(lot["units"] for lot in queue)
            bonus_numerator = before * (action["numerator"] - action["denominator"])
            bonus_units = bonus_numerator // action["denominator"]
            fractional = (
                (bonus_numerator % action["denominator"] != 0)
                if action["action_type"] == "BONUS"
                else any(
                    lot["units"] * action["numerator"] % action["denominator"] != 0 for lot in queue
                )
            )
            if fractional:
                reason = f"{action['symbol']}: fractional corporate-action entitlement requires manual reconciliation"
                if not allow_unresolved:
                    raise DomainValidationError(reason)
                unresolved[key] = {**groups[key], "reason": reason}
                continue
            if action["action_type"] == "BONUS":
                if bonus_units <= 0:
                    raise DomainValidationError("invalid bonus entitlement")
                queue.append(
                    {
                        "date": action["effective_date"],
                        "units": int(bonus_units),
                        "unit_cost": "0",
                        "trade_id": "",
                        "corporate_action": "BONUS",
                    }
                )
            else:
                for lot in queue:
                    lot["units"] = lot["units"] * action["numerator"] // action["denominator"]
                    lot["unit_cost"] = str(Decimal(lot["unit_cost"]) / factor)
            adjustments.append(
                {
                    **action,
                    "isin": groups[key]["isin"],
                    "units_before": before,
                    "units_after": sum(lot["units"] for lot in queue),
                }
            )

    for trade in sorted(trades, key=lambda item: (item["timestamp"], item["row"])):
        apply_actions(trade["date"])
        isin = resolved_isin(trade["isin"] or symbol_isins.get(trade["symbol"], ""))
        key = isin or trade["symbol"]
        queue = queues.setdefault(key, deque())
        groups.setdefault(key, {"isin": isin, "symbol": trade["symbol"]})
        if trade["side"] == "BUY":
            queue.append(
                {
                    "date": trade["date"],
                    "units": trade["units"],
                    "unit_cost": str(
                        Decimal(trade["price"]) + Decimal(trade["fee"]) / trade["units"]
                    ),
                    "trade_id": trade["trade_id"],
                }
            )
        else:
            remaining = trade["units"]
            while remaining and queue:
                matched = min(remaining, queue[0]["units"])
                remaining -= matched
                queue[0]["units"] -= matched
                if not queue[0]["units"]:
                    queue.popleft()
            if remaining:
                reason = f"{trade['symbol']}: a sell exceeds earlier buys; upload the full equity history, including older buys and corporate-action adjustments"
                if not allow_unresolved:
                    raise DomainValidationError(reason)
                unresolved[key] = {**groups[key], "reason": reason}
    apply_actions(as_of or max(trade["date"] for trade in trades))
    open_groups = [
        {**groups[key], "lots": list(queue), "units": sum(lot["units"] for lot in queue)}
        for key, queue in queues.items()
        if queue and key not in unresolved
    ]
    return {
        **parsed,
        "trades": trades,
        "open_groups": open_groups,
        "closed_symbols": sum(not queue and key not in unresolved for key, queue in queues.items()),
        "unresolved_groups": list(unresolved.values()),
        "corporate_action_adjustments": adjustments,
        "corporate_actions": list(corporate_actions),
    }
