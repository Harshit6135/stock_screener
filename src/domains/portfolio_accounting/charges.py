"""Read effective trade fees from audited charge-component records."""

from decimal import Decimal


def charge_records(connection, account_id):
    records = {}
    for row in connection.execute(
        """SELECT c.*, d.filename FROM ledger_charge_components c
           JOIN ledger_charge_documents d ON d.account_id=c.account_id AND d.document_id=c.document_id
           WHERE c.account_id=? ORDER BY c.event_version,c.charge_group,c.component""",
        (account_id,),
    ):
        records.setdefault(row["event_version"], []).append(dict(row))
    return records


def fee_breakdown(payload, records):
    contract = [row for row in records if row["charge_group"] == "contract"]
    details = {}
    if not contract and Decimal(str(payload.get("fee", "0"))):
        details["recorded_fee"] = Decimal(str(payload["fee"]))
    for row in records:
        if (
            row["component"] == "dp"
            and row["charge_group"] == "contract"
            and any(r["charge_group"] == "dp" for r in records)
        ):
            continue  # An itemized statement overrides a DP amount in a combined CSV.
        key = row["component"]
        details[key] = details.get(key, Decimal(0)) + Decimal(row["amount"])
    return details


def effective_payload(payload, event_type, version, records):
    payload = dict(payload)
    own = records.get(version, [])
    if event_type == "FILL_RECORDED":
        payload["fee"] = str(sum(fee_breakdown(payload, own).values(), Decimal(0)))
    elif event_type == "OPENING_POSITION_IMPORTED" and own:
        total = sum(fee_breakdown(payload, own).values(), Decimal(0))
        payload["unit_cost"] = str(
            Decimal(str(payload["unit_cost"])) + total / int(payload["units"])
        )
    elif event_type == "IMPORTED_POSITION_FUNDED":
        extra = sum(
            (
                sum(fee_breakdown({}, records.get(v, [])).values(), Decimal(0))
                for v in payload["import_versions"]
            ),
            Decimal(0),
        )
        payload["amount"] = str(Decimal(payload["amount"]) + extra)
    return payload


def accounting_rows(ledger, connection, account_id, rows):
    import json

    records = charge_records(connection, account_id)
    return tuple(
        ledger._parse_accounting_event(
            effective_payload(
                json.loads(row["event_json"]), row["event_type"], row["version"], records
            ),
            row["event_type"],
        )
        for row in rows
    )


TAX_DEDUCTIBLE_COMPONENTS = frozenset(
    {"brokerage", "exchange", "clearing", "sebi", "gst", "stamp_duty", "dp"}
)
