import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from flask import Flask
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.domains.portfolio_accounting import Fill, FillSide, Ledger, OpeningPosition
from src.domains.portfolio_accounting.history_import import import_history
from src.domains.portfolio_accounting.portfolio_tax import portfolio_tax_estimates
from src.gates.http.charges import create_charges_blueprint
from src.gates.http.portfolio import create_portfolio_blueprint
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.charge_documents import _parse_pdf, allocate, parse_document
from src.gates.workflows.charge_import import ChargeImport
from src.platform_kernel import DomainValidationError, Money, Quantity

HEADER = (
    "symbol,date,side,quantity,price,trade_id,brokerage,exchange_charges,sebi,gst,stt,stamp_duty\n"
)
NOTES = (
    HEADER + "ABC,2026-02-09,BUY,10,10,1,1,1,1,1,1,1\n"
    "ABC,2026-05-01,SELL,4,20,2,1,1,1,1,1,0\n"
    "XYZ,2026-05-01,SELL,4,20,9,100,0,0,0,0,0\n"
).encode()
STATEMENT = b"date,description,isin,debit,credit\n2026-05-02,DP charges,INE000000001,15,0\n2026-05-02,Other debit,INE000000001,999,0\n"


def setup(tmp_path):
    db = tmp_path / "charges.db"
    ledger, market = Ledger(db), MarketRepository(db)
    ledger.open_account("account", Money(1000), date(2026, 1, 1))
    market.upsert_instruments(
        [TrackedInstrument("abc", "INE000000001", "ABC", "NSE", "1", date(2026, 1, 1))]
    )
    ledger.record_fills(
        "account",
        "trades",
        0,
        [
            Fill(
                "abc",
                date(2026, 2, 9),
                FillSide.BUY,
                Quantity(10),
                Money(10),
                Money(1),
                broker_trade_id="1",
            ),
            Fill(
                "abc",
                date(2026, 5, 1),
                FillSide.SELL,
                Quantity(4),
                Money(20),
                Money(2),
                broker_trade_id="2",
            ),
        ],
    )
    return ledger, market, ChargeImport(ledger, market)


def command(preview):
    return {
        "preview_id": preview["preview_id"],
        "expected_version": preview["expected_version"],
        "selected_row_ids": [r["row_id"] for r in preview["rows"] if r["status"] == "MATCHED"],
        "mappings": {},
    }


def apply(importer, raw=NOTES, kind="contract"):
    preview = importer.preview("account", [("file.csv", raw)], kind=kind)
    return importer.apply("account", command(preview))


def test_fifo_cash_net_returns_tax_and_original_events(tmp_path):
    ledger, market, importer = setup(tmp_path)
    original = ledger.events("account")
    assert apply(importer)["additional_charges"] == "8.00"
    assert Decimal(apply(importer, STATEMENT, "statement")["additional_charges"]) == 15
    projection = ledger.projection("account")
    assert projection.cash.amount == 954
    assert projection.realised_pnl.amount == Decimal("17.6")
    assert projection.open_lots[0].unit_cost.amount == Decimal("10.6")
    trade = ledger.journal("account")[0]
    assert Decimal(trade["total_charges"]) == Decimal("22.4")
    assert Decimal(trade["tax_deductible_charges"]) == 21
    assert trade["charges_complete"]
    assert Decimal(trade["buy_charges"]["stamp_duty"]) == Decimal("0.4")
    assert Decimal(trade["sell_charges"]["dp"]) == 15
    assert Decimal(
        portfolio_tax_estimates([trade], date(2026, 10, 7))[0]["estimated_tax"]
    ) == Decimal("3.95")
    assert ledger.events("account")[:2] == original
    assert ledger.events("account")[-1]["event_type"] == "CHARGES_RECONCILED"
    with pytest.raises(DomainValidationError, match="withdrawal exceeds"):
        ledger.record_cash_transfer("account", "withdraw", 4, "WITHDRAW", Money(955), reason="test")
    app = Flask(__name__)
    app.register_blueprint(create_portfolio_blueprint(ledger, market))
    result = app.test_client().get("/api/portfolio/accounts/account/journal").json
    assert Decimal(result["journal"][0]["total_charges"]) == Decimal("22.4")


def test_duplicate_files_rows_and_replacement_do_not_add_twice(tmp_path):
    ledger, _, importer = setup(tmp_path)
    preview = importer.preview("account", [("one.csv", NOTES), ("two.csv", NOTES)])
    assert preview["matched_rows"] == 2
    assert preview["outside_rows"] == 1
    cmd = command(preview)
    result = importer.apply("account", cmd)
    assert importer.apply("account", cmd) == result
    assert apply(importer)["duplicate"]
    assert len(ledger.events("account")) == 3
    amended = NOTES.replace(b"BUY,10,10,1,1,1,1,1,1,1", b"BUY,10,10,1,1,1,1,2,1,1")
    assert apply(importer, amended)["additional_charges"] == "1.00"
    assert ledger.projection("account").cash.amount == 968
    doubled = NOTES + NOTES.decode().splitlines()[1].encode() + b"\n"
    assert importer.preview("account", [("duplicate-row.csv", doubled)])["matched_rows"] == 2


def test_atomic_cash_guard_stale_preview_and_account_scope(tmp_path):
    ledger, _, importer = setup(tmp_path)
    preview = importer.preview(
        "account", [("high.csv", NOTES.replace(b"BUY,10,10,1,1,", b"BUY,10,10,1,1000,"))]
    )
    with pytest.raises(DomainValidationError, match="buy fill exceeds"):
        importer.apply("account", command(preview))
    assert ledger.projection("account").cash.amount == 977
    assert len(ledger.events("account")) == 2
    with ledger._connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM ledger_charge_components").fetchone()[0] == 0
        )
    preview = importer.preview("account", [("note.csv", NOTES)])
    ledger.open_account("other", Money(1000))
    with pytest.raises(DomainValidationError, match="does not exist for this account"):
        importer.apply("other", command(preview))
    apply(importer)
    with pytest.raises(DomainValidationError, match="ledger changed"):
        importer.apply("account", command(preview))


def test_overlapping_documents_need_consistent_charges(tmp_path):
    ledger, _, importer = setup(tmp_path)
    preview = importer.preview(
        "account",
        [("one.csv", NOTES), ("two.csv", NOTES.replace(b"BUY,10,10,1,1,", b"BUY,10,10,1,2,"))],
    )
    with pytest.raises(DomainValidationError, match="overlapping documents disagree"):
        importer.apply("account", command(preview))
    assert ledger.projection("account").cash.amount == 977


def test_dp_ambiguous_sale_dates_require_manual_mapping(tmp_path):
    ledger, _, importer = setup(tmp_path)
    ledger.record_fills(
        "account",
        "sell2",
        2,
        [Fill("abc", date(2026, 5, 2), FillSide.SELL, Quantity(2), Money(20), broker_trade_id="3")],
    )
    preview = importer.preview("account", [("dp.csv", STATEMENT)], kind="statement")
    row = preview["rows"][0]
    assert row["status"] == "AMBIGUOUS"
    cmd = command(preview)
    cmd.update(selected_row_ids=[row["row_id"]], mappings={row["row_id"]: 2})
    importer.apply("account", cmd)
    trades = ledger.journal("account")
    assert Decimal(trades[0]["sell_charges"]["dp"]) == 15
    assert "dp" not in trades[1]["sell_charges"]


def encrypted_pdf(lines):
    writer = PdfWriter()
    page = writer.add_blank_page(1200, 1000)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        (
            "BT /F1 10 Tf 10 980 Td " + " ".join(f"({line}) Tj 0 -20 Td" for line in lines) + " ET"
        ).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.encrypt("secret", algorithm="AES-256")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_encrypted_pdf_allocates_including_outside_trades_and_gst_once(tmp_path):
    _, _, importer = setup(tmp_path)
    raw = encrypted_pdf(
        [
            "Trade Date: 09-02-2026",
            "123456789 09:30:00 1 09:30:01 ABC B NSE 10 - 10.00 0.00 10.00 - -100.00",
            "123456789 09:30:00 9 09:30:01 XYZ B NSE 10 - 10.00 0.00 10.00 - -100.00",
            "Exchange charges 10.00",
            "CGST 1.00",
            "SGST 1.00",
            "GST 2.00",
        ]
    )
    rows, warnings = parse_document("note.pdf", raw, "secret")
    assert len(rows) == 2
    assert rows[0]["estimated"] and warnings
    assert Decimal(rows[0]["components"]["exchange"]) == 5
    assert Decimal(rows[0]["components"]["gst"]) == 1
    with pytest.raises(DomainValidationError, match="password"):
        parse_document("note.pdf", raw, "wrong")
    preview = importer.preview("account", [("bad.pdf", raw), ("good.csv", NOTES)], "wrong")
    assert preview["matched_rows"] == 2
    assert "password" in preview["documents"][0]["warnings"][0]
    with importer.ledger._connect() as connection:
        stored = connection.execute("SELECT payload_json FROM ledger_charge_previews").fetchone()[0]
        assert "wrong" not in stored and "secret" not in stored


def test_xlsx_dp_debits_only_and_normalized_gst_totals():
    book = Workbook()
    sheet = book.active
    sheet.append(["date", "description", "isin", "debit", "credit"])
    sheet.append(["2026-05-02", "DP charges", "INE000000001", 15, 0])
    sheet.append(["2026-05-02", "DP refund", "INE000000001", 0, 15])
    stream = io.BytesIO()
    book.save(stream)
    rows, warnings = parse_document("dp.xlsx", stream.getvalue(), kind="statement")
    assert len(rows) == 1 and warnings
    assert rows[0]["components"] == {"dp": "15"}
    raw = (
        b"symbol,date,side,quantity,price,gst,cgst,sgst,charges\nABC,2026-02-09,BUY,10,10,2,1,1,2\n"
    )
    rows, warnings = parse_document("gst.csv", raw)
    assert rows[0]["components"]["gst"] == "2" and not warnings
    assert sum(allocate(Decimal("0.01"), [Decimal(1), Decimal(1)])) == Decimal("0.01")


def test_http_batch_and_invalid_commands_return_validation_errors(tmp_path):
    ledger, _, importer = setup(tmp_path)
    app = Flask(__name__)
    app.register_blueprint(create_charges_blueprint(importer))
    client = app.test_client()
    root = "/api/portfolio/accounts/account/charges"
    response = client.post(
        root + "/preview",
        data={"files": [(io.BytesIO(NOTES), "note.csv"), (io.BytesIO(STATEMENT), "statement.csv")]},
    )
    assert response.status_code == 200
    preview = response.json
    assert client.post(root + "/apply", json=command(preview)).status_code == 200
    assert ledger.projection("account").cash.amount == 954
    cmd = command(preview)
    cmd["selected_row_ids"] = [{}]
    assert client.post(root + "/apply", json=cmd).status_code == 400
    assert client.post(root + "/apply", json=None).status_code == 400
    assert client.get("/api/portfolio/accounts/charges/template.csv").status_code == 200


def test_funded_opening_lot_buy_charges(tmp_path):
    ledger, _, importer = setup(tmp_path)
    ledger.open_account("imported", Money(1000), date(2026, 1, 1))
    ledger.import_opening_positions(
        "imported",
        "snapshot",
        0,
        [
            OpeningPosition(
                "abc",
                date(2026, 2, 9),
                Quantity(10),
                Money(10),
                datetime(2026, 2, 9, tzinfo=UTC),
                json.dumps({"source": "kite-opening-balance", "broker_account_id": "imported"}),
            )
        ],
    )
    ledger.fund_broker_imports("imported", "imported")
    preview = importer.preview(
        "imported", [("buy.csv", (HEADER + "ABC,2026-02-09,BUY,10,10,1,1,1,1,1,1,1\n").encode())]
    )
    assert preview["matched_rows"] == 1
    importer.apply("imported", command(preview))
    assert ledger.projection("imported").cash.amount == 894
    assert ledger.projection("imported").open_lots[0].unit_cost.amount == Decimal("10.6")
    # Imported capital basis remains attributed to the account, not to outside stocks.
    assert ledger.projection("account").cash.amount == 977


def test_partial_sales_conserve_buy_fees_and_history_remains_idempotent(tmp_path):
    ledger, _, importer = setup(tmp_path)
    apply(importer)
    ledger.record_fills(
        "account",
        "remaining",
        3,
        [
            Fill(
                "abc",
                date(2026, 6, 1),
                FillSide.SELL,
                Quantity(6),
                Money(20),
                broker_trade_id="3",
            )
        ],
    )
    trades = ledger.journal("account")
    assert sum(Decimal(t["buy_charges"]["brokerage"]) for t in trades) == 1
    assert (
        sum(Decimal(t["realised_pnl"]) for t in trades)
        == ledger.projection("account").realised_pnl.amount
    )
    assert ledger.projection_at("account", date(2026, 2, 9)).cash.amount == 894
    fills = [
        Fill(
            "abc",
            date(2026, 2, 9),
            FillSide.BUY,
            Quantity(10),
            Money(10),
            Money(1),
            broker_trade_id="1",
        )
    ]
    result = import_history(ledger, "account", "repeat", 4, fills)
    assert result["duplicate_trades"] == 1


def modern_note(extra_trade=False):
    def charge(label, cash="", derivatives="", total=None):
        return f"{label:<90}{cash:>15}{derivatives:>40}{(cash if total is None else total):>40}"

    lines = [
        "Trade Date:    23/03/2026",
        "Net Obligation for ISIN",
        "INE000000001  ABC  0  0.0000  0.0000  0.0000  0.00  45  274.7000  0.0000  274.7000  12361.50  -45  12361.50",
        charge("", "NCL-Cash", "NCL-F&O", "NET TOTAL"),
        charge("Pay in/Pay out obligation", "12361.50", "99.00", "12460.50"),
        charge("Taxable value of Supply (Brokerage)", "(0.01)", "(10.00)", "(10.01)"),
        charge("Exchange transaction charges", "(0.38)", "(20.00)", "(20.38)"),
        charge("Clearing charges"),
        charge("CGST (@9% of Brok, SEBI, Trans & Clearing Charges)"),
        charge("SGST (@9% of Brok, SEBI, Trans & Clearing Charges)"),
        charge("IGST (@18% of Brok, SEBI, Trans & Clearing Charges)", "(0.07)", "(5.00)", "(5.07)"),
        charge("Securities transaction tax", "(12.00)", "(8.00)", "(20.00)"),
        charge("SEBI turnover fees", "(0.01)"),
        charge("Stamp duty"),
        charge("Net amount receivable/(payable by client)", "12349.03", "56.00", "12405.03"),
        "Annexure A Equity Net Rate per Unit",
        "1200000000000000  09:30:37  12345  09:30:37  ABC-EQ/INE000000001  S  NSE  45  0.0000  274.70  12361.50",
    ]
    if extra_trade:
        lines.insert(
            3,
            "INE000000002  XYZ  0  0.0000  0.0000  0.0000  0.00  45  274.7000  0.0000  274.7000  12361.50  -45  12361.50",
        )
        lines.append(
            "1200000000000001  09:30:37  12346  09:30:37  XYZ-EQ/INE000000002  S  NSE  45  0.0000  274.70  12361.50"
        )
        lines = [
            line.replace("12361.50", "24723.00")
            if line.startswith("Pay in/Pay out obligation")
            else line.replace("12349.03", "24710.53")
            if line.startswith("Net amount receivable")
            else line
            for line in lines
        ]
    return "\n".join(lines)


def test_modern_zerodha_cash_annexure_and_repeated_totals():
    rows, warnings = _parse_pdf(modern_note(), "contract")
    assert not warnings and len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "ABC" and row["isin"] == "INE000000001"
    assert row["units"] == 45 and row["side"] == "SELL"
    assert Decimal(row["price"]) == Decimal("274.70")
    assert sum(Decimal(v) for v in row["components"].values()) == Decimal("12.47")
    assert row["components"]["brokerage"] == "0.01"
    assert row["components"]["gst"] == "0.07"
    assert not row["estimated"]  # One equity trade; all cash fees belong to it.


def test_modern_zerodha_outside_trades_receive_their_own_allocation():
    rows, warnings = _parse_pdf(modern_note(True), "contract")
    assert len(rows) == 2 and warnings
    assert all(row["estimated"] for row in rows)
    assert sum(sum(Decimal(v) for v in row["components"].values()) for row in rows) == Decimal(
        "12.47"
    )
    assert sum(Decimal(v) for v in rows[0]["components"].values()) < Decimal("12.47")


@pytest.mark.parametrize(
    "change",
    [
        lambda text: text.replace("S  NSE  45", "S  NSE  44"),
        lambda text: text.replace("12349.03", "12348.03"),
        lambda text: text.replace("SEBI turnover fees", "Unknown fees"),
        lambda text: text.replace("ABC-EQ/INE000000001", "ABC-EQ/UNKNOWN"),
    ],
)
def test_modern_zerodha_incomplete_or_inconsistent_note_is_not_allocated(change):
    rows, warnings = _parse_pdf(change(modern_note()), "contract")
    assert not rows and warnings


def test_modern_brokerage_does_not_change_execution_price():
    text = modern_note().replace("45  0.0000  274.70", "45  0.0002  274.70")
    rows, warnings = _parse_pdf(text, "contract")
    assert not warnings
    assert Decimal(rows[0]["price"]) == Decimal("274.70")
    assert Decimal(rows[0]["components"]["brokerage"]) == Decimal("0.01")


def test_modern_purchase_signed_obligations_and_stamp_duty():
    text = modern_note()
    text = text.replace(
        "0  0.0000  0.0000  0.0000  0.00  45  274.7000  0.0000  274.7000  12361.50  -45  12361.50",
        "45  274.7000  0.0000  274.7000  12361.50  0  0.0000  0.0000  0.0000  0.00  45  -12361.50",
    )
    text = text.replace(
        "S  NSE  45  0.0000  274.70  12361.50", "B  NSE  45  0.0000  274.70  -12361.50"
    )
    lines = []
    for line in text.splitlines():
        if line.startswith("Pay in/Pay out obligation"):
            line = (
                f"{'Pay in/Pay out obligation':<90}{'(12361.50)':>15}{'0.00':>40}{'(12361.50)':>40}"
            )
        if line.startswith("Stamp duty"):
            line = f"{'Stamp duty':<90}{'(2.00)':>15}{'':>40}{'(2.00)':>40}"
        if line.startswith("Net amount receivable/(payable by client)"):
            line = f"{'Net amount receivable/(payable by client)':<90}{'(12375.97)':>15}{'0.00':>40}{'(12375.97)':>40}"
        lines.append(line)
    rows, warnings = _parse_pdf("\n".join(lines), "contract")
    assert not warnings and rows[0]["side"] == "BUY"
    assert Decimal(rows[0]["components"]["stamp_duty"]) == 2


def test_bse_execution_uses_original_exchange_with_listing_on_nse(tmp_path):
    ledger, _, importer = setup(tmp_path)
    ledger.open_account("bse", Money(1000), date(2026, 1, 1))
    ledger.record_fills(
        "bse",
        "buy",
        0,
        [
            Fill(
                "abc",
                date(2026, 2, 9),
                FillSide.BUY,
                Quantity(10),
                Money(10),
                broker_trade_id="tradebook:BSE:2026-02-09:100",
            )
        ],
    )
    raw = b"symbol,date,side,quantity,price,trade_id,exchange,gst\nABC-B,2026-02-09,BUY,10,10,100,BSE,2\n"
    preview = importer.preview("bse", [("bse.csv", raw)])
    assert preview["matched_rows"] == 1
    assert preview["rows"][0]["symbol"] == "ABC"
    importer.apply("bse", command(preview))
    assert ledger.projection("bse").cash.amount == 898
    wrong_exchange = raw.replace(b",BSE,", b",NSE,")
    assert importer.preview("bse", [("wrong.csv", wrong_exchange)])["matched_rows"] == 0


def test_historical_isin_change_needs_exact_execution_id_and_trade_details(tmp_path):
    ledger, _, importer = setup(tmp_path)
    raw = b"symbol,isin,date,side,quantity,price,trade_id,exchange,gst\nABC-SM,INE000000999,2026-02-09,BUY,10,10,1,NSE,2\n"
    preview = importer.preview("account", [("historical.csv", raw)])
    assert preview["matched_rows"] == 1
    for wrong in [
        raw.replace(b",1,NSE", b",9,NSE"),
        raw.replace(b",10,10,1", b",11,10,1"),
        raw.replace(b"ABC-SM", b"XYZ-SM"),
    ]:
        assert importer.preview("account", [("wrong.csv", wrong)])["matched_rows"] == 0
    assert ledger.projection("account").cash.amount == 977  # Preview never applies fees.
