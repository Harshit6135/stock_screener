"""Review and atomically reconcile charges against an account's actual trade events."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.domains.portfolio_accounting.api import project
from src.domains.portfolio_accounting.charges import accounting_rows, charge_records, fee_breakdown
from src.domains.portfolio_accounting.tradebook import canonical_symbol
from src.gates.workflows.charge_documents import COMPONENT_LABELS, allocate, amount, parse_document
from src.platform_kernel import DomainValidationError, Money


class ChargeImport:
    def __init__(self, ledger, market):
        self.ledger, self.market = ledger, market

    def _targets(self, account_id):
        events = self.ledger.events(account_id)
        funded = {
            v
            for e in events
            if e["event_type"] == "IMPORTED_POSITION_FUNDED"
            for v in e["event"]["import_versions"]
        }
        result = []
        for event in events:
            payload, kind = event["event"], event["event_type"]
            if kind not in {"FILL_RECORDED", "OPENING_POSITION_IMPORTED"}:
                continue
            if kind == "OPENING_POSITION_IMPORTED" and event["version"] not in funded:
                continue
            identity = self.market.instrument_by_id(payload["instrument_id"])
            if not identity:
                continue
            trade_id = payload.get("broker_trade_id", "") or ""
            original_exchange = re.match(r"^tradebook:(NSE|BSE):\d{4}-\d{2}-\d{2}:", trade_id)
            result.append(
                {
                    "version": event["version"],
                    "symbol": canonical_symbol(identity["symbol"]),
                    "isin": identity["isin"],
                    "exchange": original_exchange.group(1)
                    if original_exchange
                    else identity["exchange"],
                    "date": payload.get("fill_date", payload.get("acquisition_date")),
                    "side": payload.get("side", "BUY"),
                    "units": int(payload["units"]),
                    "price": str(payload.get("price", payload.get("unit_cost"))),
                    "trade_id": payload.get("broker_trade_id", ""),
                    "kind": kind,
                    "basis_replaced": payload.get("side", "BUY") == "BUY"
                    and any(
                        later["version"] > event["version"]
                        and later["event_type"] == "OPEN_LOTS_RECONCILED"
                        and later["event"].get("instrument_id") == payload["instrument_id"]
                        for later in events
                    ),
                    "original_fee": str(payload.get("fee", "0")),
                }
            )
        return result

    def preview(self, account_id, files, password="", kind="contract"):
        if kind not in {"contract", "statement"}:
            raise DomainValidationError("choose contract notes or DP statements")
        if not 1 <= len(files) <= 50 or sum(len(raw) for _, raw in files) > 64 * 1024 * 1024:
            raise DomainValidationError("upload 1..50 files, totaling no more than 64 MB")
        accounts = self.ledger.accounts()
        account = next((a for a in accounts if a["account_id"] == account_id), None)
        if account is None:
            raise DomainValidationError("account does not exist")
        targets = self._targets(account_id)
        documents, rows, seen_documents = [], [], set()
        for filename, raw in files:
            filename = Path(filename).name[:160]
            document_id = hashlib.sha256(raw).hexdigest()
            if document_id in seen_documents:
                documents.append(
                    {
                        "document_id": document_id,
                        "filename": filename,
                        "warnings": ["Duplicate file within this batch; ignored."],
                        "row_count": 0,
                    }
                )
                continue
            seen_documents.add(document_id)
            try:
                parsed, warnings = parse_document(filename, raw, password, kind)
            except (DomainValidationError, OSError, ValueError) as exc:
                parsed, warnings = [], [str(exc)]
            document = {
                "document_id": document_id,
                "filename": filename,
                "warnings": warnings,
                "row_count": len(parsed),
            }
            documents.append(document)
            seen_rows = set()
            for index, row in enumerate(parsed):
                signature = json.dumps(
                    {k: v for k, v in row.items() if k != "line"}, sort_keys=True
                )
                if signature in seen_rows:
                    document["warnings"].append(f"Duplicate source row {row['line']}; ignored.")
                    continue
                seen_rows.add(signature)
                rows.append(
                    {
                        **row,
                        "row_id": f"{document_id}:{index}",
                        "document_id": document_id,
                        "filename": filename,
                    }
                )
        if len(rows) > 20000:
            raise DomainValidationError("charge batch exceeds 20,000 transactions")
        for row in rows:
            self._match(row, targets, rows)
        preview_id = str(uuid4())
        payload = {
            "preview_id": preview_id,
            "account_id": account_id,
            "expected_version": account["version"],
            "documents": documents,
            "rows": rows,
            "targets": targets,
            "component_labels": COMPONENT_LABELS,
            "matched_rows": sum(r["status"] == "MATCHED" for r in rows),
            "outside_rows": sum(r["status"] == "OUTSIDE" for r in rows),
        }
        with self.ledger._connect() as connection:
            connection.execute(
                "INSERT INTO ledger_charge_previews VALUES (?,?,?,?,NULL)",
                (account_id, preview_id, json.dumps(payload), datetime.now(UTC).isoformat()),
            )
        return payload

    @staticmethod
    def _same_stock(row, target):
        if row.get("isin"):
            if row["isin"].strip().upper() == target["isin"].strip().upper():
                return True
            # Current instrument identifiers may follow a split/ISIN change.
            # Only an exact execution ID with the same normalized symbol can
            # bridge that mismatch; date, exchange, quantity and price are
            # still checked by _match. DP postings have no such execution ID.
            return (
                row["group"] == "contract"
                and bool(row.get("trade_id"))
                and bool(target.get("trade_id"))
                and target["trade_id"].split(":")[-1] == row["trade_id"]
                and canonical_symbol(row.get("symbol", "")) == canonical_symbol(target["symbol"])
            )
        return bool(row.get("symbol")) and canonical_symbol(row["symbol"]) == target["symbol"]

    def _match(self, row, targets, rows):
        if date.fromisoformat(row["date"]) > datetime.now(ZoneInfo("Asia/Kolkata")).date():
            row.update(
                status="INVALID",
                reason="Document date is in the future.",
                match_versions=[],
                candidate_versions=[],
            )
            return
        candidates = [
            t
            for t in targets
            if self._same_stock(row, t)
            and t["side"] == row["side"]
            and t["exchange"] == row["exchange"]
        ]
        if row["group"] == "dp":
            day = date.fromisoformat(row["date"])
            candidates = [
                t for t in candidates if 0 <= (day - date.fromisoformat(t["date"])).days <= 7
            ]
            sale_dates = {t["date"] for t in candidates}
            if len(sale_dates) == 1:
                row["match_versions"] = [t["version"] for t in candidates]
                row["status"] = "MATCHED"
                row["reason"] = (
                    "DP debit matched to stock and sale date; split across same-day executions by units."
                )
            else:
                row["match_versions"] = []
                row["status"] = (
                    "AMBIGUOUS"
                    if candidates or not row.get("symbol") and not row.get("isin")
                    else "OUTSIDE"
                )
                row["reason"] = (
                    "Choose the sale this DP debit belongs to."
                    if row["status"] == "AMBIGUOUS"
                    else "No recorded sale for this stock near the statement date."
                )
        else:
            candidates = [t for t in candidates if t["date"] == row["date"]]
            exact = [
                t
                for t in candidates
                if t["units"] == row["units"]
                and abs(Decimal(t["price"]) - Decimal(row["price"])) <= Decimal("0.01")
            ]
            if row.get("trade_id"):
                by_id = [
                    t
                    for t in exact
                    if t["trade_id"]
                    and (
                        t["trade_id"] == row["trade_id"]
                        or t["trade_id"].split(":")[-1] == row["trade_id"]
                    )
                ]
                exact = by_id or [
                    t for t in exact if not t["trade_id"] or len(t["trade_id"].split(":")[-1]) == 64
                ]
            # A cash-funded broker snapshot may summarize several fills in one lot.
            if not exact:
                siblings = [
                    r
                    for r in rows
                    if r["document_id"] == row["document_id"]
                    and r["date"] == row["date"]
                    and r["symbol"] == row["symbol"]
                    and r["side"] == row["side"]
                    and r["group"] == "contract"
                ]
                quantity = sum(r["units"] for r in siblings)
                weighted = sum((Decimal(r["price"]) * r["units"] for r in siblings), Decimal(0))
                exact = [
                    t
                    for t in candidates
                    if t["kind"] == "OPENING_POSITION_IMPORTED"
                    and t["units"] == quantity
                    and quantity
                    and abs(Decimal(t["price"]) - weighted / quantity) <= Decimal("0.01")
                ]
            row["match_versions"] = [t["version"] for t in exact] if len(exact) == 1 else []
            row["status"] = (
                "MATCHED" if len(exact) == 1 else "AMBIGUOUS" if len(exact) > 1 else "OUTSIDE"
            )
            row["reason"] = (
                "Matched stock, date, side, quantity and price."
                if len(exact) == 1
                else "Multiple identical executions; choose the correct trade."
                if exact
                else "No matching recorded transaction; ignored."
            )
            if (
                len(exact) == 1
                and row.get("isin")
                and row["isin"].upper() != exact[0]["isin"].upper()
            ):
                row["reason"] = (
                    "Matched exact execution ID, stock, date, exchange, quantity and price; historical ISIN differs from the current instrument."
                )
            if any(t["basis_replaced"] for t in exact):
                row.update(
                    status="INVALID",
                    match_versions=[],
                    reason="Purchase basis was replaced by an open-lot reconciliation. Import complete history into a fresh portfolio before reconciling its buy charges.",
                )
                exact = []
        row["candidate_versions"] = [
            t["version"] for t in (candidates if row["group"] == "dp" else exact)
        ]
        if (
            row["group"] == "dp"
            and not candidates
            and not row.get("symbol")
            and not row.get("isin")
        ):
            row["candidate_versions"] = [
                t["version"]
                for t in targets
                if t["side"] == "SELL"
                and 0 <= (date.fromisoformat(row["date"]) - date.fromisoformat(t["date"])).days <= 7
            ]

    def apply(self, account_id, command):
        if not isinstance(command, dict) or set(command) != {
            "preview_id",
            "expected_version",
            "selected_row_ids",
            "mappings",
        }:
            raise DomainValidationError("charge import command is invalid")
        selected, mappings = command["selected_row_ids"], command["mappings"]
        if (
            not isinstance(selected, list)
            or not selected
            or not all(isinstance(value, str) for value in selected)
            or len(selected) != len(set(selected))
            or not isinstance(mappings, dict)
            or not isinstance(command["preview_id"], str)
            or isinstance(command["expected_version"], bool)
            or not isinstance(command["expected_version"], int)
        ):
            raise DomainValidationError("select charge rows to apply")
        with self.ledger._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored = connection.execute(
                "SELECT * FROM ledger_charge_previews WHERE account_id=? AND preview_id=?",
                (account_id, command["preview_id"]),
            ).fetchone()
            if stored is None:
                raise DomainValidationError("charge preview does not exist for this account")
            payload = json.loads(stored["payload_json"])
            checksum = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
            if stored["result_json"]:
                previous = json.loads(stored["result_json"])
                if previous["command_checksum"] != checksum:
                    raise DomainValidationError(
                        "this preview was already applied with another selection"
                    )
                return previous
            current = connection.execute(
                "SELECT COALESCE(MAX(version),0) FROM ledger_events WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
            if current != command["expected_version"] or payload["expected_version"] != current:
                raise DomainValidationError("ledger changed; preview the files again")
            targets = {t["version"]: t for t in payload["targets"]}
            row_map = {r["row_id"]: r for r in payload["rows"]}
            if not set(selected) <= row_map.keys() or not set(mappings) <= set(selected):
                raise DomainValidationError("selection contains unknown charge rows")
            plan, source_rows = {}, {}
            for row_id in selected:
                row = row_map[row_id]
                versions = row["match_versions"]
                if row_id in mappings:
                    chosen = mappings[row_id]
                    if (
                        isinstance(chosen, bool)
                        or not isinstance(chosen, int)
                        or chosen not in row["candidate_versions"]
                    ):
                        raise DomainValidationError(
                            "manual mapping must use a listed matching trade"
                        )
                    versions = [chosen]
                    if row["group"] == "dp":
                        chosen_target = targets[chosen]
                        versions = [
                            t["version"]
                            for t in targets.values()
                            if t["version"] in row["candidate_versions"]
                            and t["isin"] == chosen_target["isin"]
                            and t["date"] == chosen_target["date"]
                        ]
                if not versions:
                    raise DomainValidationError("resolve ambiguous rows or uncheck them")
                source_rows.setdefault(
                    (row["document_id"], tuple(versions), row["group"]), []
                ).append(row)
            # Different documents claiming the same execution must agree. Never
            # silently add overlapping notes or apply last-document-wins logic.
            for (_document_id, versions, group), rows in source_rows.items():
                components = {}
                estimated = any(r["estimated"] for r in rows) or len(versions) > 1
                for row in rows:
                    for component, value in row["components"].items():
                        if component not in COMPONENT_LABELS or component == "recorded_fee":
                            raise DomainValidationError("unknown charge component")
                        components[component] = components.get(component, Decimal(0)) + amount(
                            value
                        )
                weights = [Decimal(targets[v]["units"]) for v in versions]
                shares = {k: allocate(v, weights) for k, v in components.items()}
                for index, version in enumerate(versions):
                    key = (version, group)
                    entry = {
                        "components": {k: str(values[index]) for k, values in shares.items()},
                        "document_id": rows[0]["document_id"],
                        "estimated": estimated,
                    }
                    if key in plan and plan[key]["components"] != entry["components"]:
                        raise DomainValidationError(
                            "overlapping documents disagree on charges for one trade; select one source"
                        )
                    plan[key] = entry
            # Multi-fill snapshot imports must retain the whole document's purchase charge basis.
            for version, _group in plan:
                if targets[version]["kind"] == "OPENING_POSITION_IMPORTED":
                    related = [
                        r["row_id"]
                        for r in payload["rows"]
                        if version in r["match_versions"] and r["group"] == "contract"
                    ]
                    if not set(related) <= set(selected):
                        raise DomainValidationError(
                            "select all charge rows for a summarized imported holding"
                        )
            before = charge_records(connection, account_id)
            changes = []
            now = datetime.now(UTC).isoformat()
            docs = {d["document_id"]: d for d in payload["documents"]}
            for (version, group), entry in plan.items():
                prior = {
                    r["component"]: str(Decimal(r["amount"]))
                    for r in before.get(version, [])
                    if r["charge_group"] == group
                }
                if prior.keys() == entry["components"].keys() and all(
                    Decimal(prior[k]) == Decimal(v) for k, v in entry["components"].items()
                ):
                    continue
                doc = docs[entry["document_id"]]
                connection.execute(
                    "INSERT OR IGNORE INTO ledger_charge_documents VALUES (?,?,?,?)",
                    (account_id, entry["document_id"], doc["filename"], now),
                )
                connection.execute(
                    "DELETE FROM ledger_charge_components WHERE account_id=? AND event_version=? AND charge_group=?",
                    (account_id, version, group),
                )
                for component, value in entry["components"].items():
                    connection.execute(
                        "INSERT INTO ledger_charge_components VALUES (?,?,?,?,?,?,?)",
                        (
                            account_id,
                            version,
                            group,
                            component,
                            value,
                            entry["document_id"],
                            int(entry["estimated"]),
                        ),
                    )
                changes.append(
                    {
                        "event_version": version,
                        "group": group,
                        "before": prior,
                        "after": entry["components"],
                        "document_id": entry["document_id"],
                        "estimated": entry["estimated"],
                    }
                )
            after = charge_records(connection, account_id)
            account = connection.execute(
                "SELECT * FROM ledger_accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            accounting = connection.execute(
                """SELECT version,event_json,event_type FROM ledger_events WHERE account_id=?
                   AND event_type IN ('FILL_RECORDED','OPENING_POSITION_IMPORTED','IMPORTED_POSITION_FUNDED',
                                      'OPEN_LOTS_RECONCILED','STOCK_SPLIT_APPLIED') ORDER BY version""",
                (account_id,),
            ).fetchall()
            transfers = sum(
                (
                    Decimal(json.loads(r[0])["amount"])
                    * (1 if json.loads(r[0])["direction"] == "DEPOSIT" else -1)
                    for r in connection.execute(
                        "SELECT event_json FROM ledger_events WHERE account_id=? AND event_type='CASH_TRANSFER'",
                        (account_id,),
                    )
                ),
                Decimal(0),
            )
            project(
                Money(Decimal(account["opening_cash"]) + transfers, account["currency"]),
                accounting_rows(self.ledger, connection, account_id, accounting),
            )
            delta = Decimal(0)
            for version in {v for v, _ in plan}:
                base = {"fee": targets[version]["original_fee"]}
                delta += sum(
                    fee_breakdown(base, after.get(version, [])).values(), Decimal(0)
                ) - sum(fee_breakdown(base, before.get(version, [])).values(), Decimal(0))
            if changes:
                current += 1
                connection.execute(
                    "INSERT INTO ledger_events(account_id,version,event_type,event_json,occurred_at) VALUES (?,?,?,?,?)",
                    (
                        account_id,
                        current,
                        "CHARGES_RECONCILED",
                        json.dumps(
                            {
                                "preview_id": command["preview_id"],
                                "changes": changes,
                                "fee_delta": str(delta),
                            },
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
            result = {
                "version": current,
                "updated_trades": len({c["event_version"] for c in changes}),
                "additional_charges": str(delta),
                "duplicate": not bool(changes),
                "command_checksum": checksum,
            }
            connection.execute(
                "UPDATE ledger_charge_previews SET result_json=? WHERE account_id=? AND preview_id=?",
                (json.dumps(result), account_id, command["preview_id"]),
            )
            return result
