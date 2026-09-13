"""Exercise the real portfolio HTTP routes against an isolated paper account."""

from datetime import date
from tempfile import TemporaryDirectory
from uuid import uuid4

from run import create_app
from src.application.market_repository import TrackedInstrument
from src.application.runtime import RuntimeConfig


def main() -> int:
    with TemporaryDirectory() as root:

        class SmokeConfig(RuntimeConfig):
            DATA_DIRECTORY = root
            OPERATOR_TOKEN = "smoke-only-token"

        app = create_app(SmokeConfig)
        services = app.extensions["screener_services"]
        services.market.upsert_instruments(
            [TrackedInstrument(str(uuid4()), "INE000000001", "ABC", "NSE", "42", date(2026, 9, 1))]
        )
        client = app.test_client()
        headers = {"X-Operator-Token": "smoke-only-token"}
        opened = client.post(
            "/api/v2/portfolio/accounts",
            json={"account_id": "paper", "opening_cash": "1000"},
            headers=headers,
        )
        if opened.status_code != 201:
            raise RuntimeError("paper account creation failed")
        buy = client.post(
            "/api/v2/portfolio/accounts/paper/fills",
            json={
                "idempotency_key": "buy-1",
                "expected_version": 0,
                "fills": [
                    {
                        "symbol": "ABC",
                        "fill_date": "2026-09-02",
                        "side": "BUY",
                        "units": 2,
                        "price": "100",
                    }
                ],
            },
            headers=headers,
        )
        if buy.status_code != 201:
            raise RuntimeError("paper buy fill failed")
        sell = client.post(
            "/api/v2/portfolio/accounts/paper/fills",
            json={
                "idempotency_key": "sell-1",
                "expected_version": 1,
                "fills": [
                    {
                        "symbol": "ABC",
                        "fill_date": "2026-09-03",
                        "side": "SELL",
                        "units": 1,
                        "price": "110",
                    }
                ],
            },
            headers=headers,
        )
        if sell.status_code != 201:
            raise RuntimeError("paper sell fill failed")
        account = client.get("/api/v2/portfolio/accounts/paper", headers=headers)
        events = client.get("/api/v2/portfolio/accounts/paper/events", headers=headers)
        if (
            account.status_code != 200
            or account.json["cash"] != "910"
            or account.json["realised_pnl"] != "10"
            or account.json["open_lots"][0]["units"] != 1
            or len(events.json["events"]) != 2
        ):
            raise RuntimeError("paper portfolio projection or event readback failed")
        print("paper_portfolio_verified=account,buy,sell,FIFO,events", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
