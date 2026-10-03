from flask import Flask

from src.domains.portfolio_accounting import Ledger
from src.gates.http.broker import create_broker_blueprint
from src.gates.workflows.broker_orders import BrokerOrderWorkflow


class FakeBroker:
    def submit_order(self, order):
        return "broker-1"

    def order_status(self, broker_order_id):
        return {
            "status": "PARTIAL",
            "fills": [
                {"trade_id": "trade-1", "quantity": 2, "price": "10", "fill_date": "2026-09-10"}
            ],
        }


def test_execution_controls_readback_is_operator_protected(tmp_path):
    database = tmp_path / "system.db"
    orders = BrokerOrderWorkflow(database, Ledger(database), FakeBroker())
    app = Flask(__name__)
    app.register_blueprint(create_broker_blueprint(orders))
    client = app.test_client()
    assert client.get("/api/v2/portfolio/execution-controls").status_code == 200
    response = client.get("/api/v2/portfolio/execution-controls")
    assert response.status_code == 200
    assert response.json["gateway"] == "FakeBroker"
