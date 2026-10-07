from datetime import date
from types import SimpleNamespace

from src.domains.artifacts import ArtifactCatalog, ArtifactPublisher
from src.domains.portfolio_accounting import Fill, FillSide, Ledger
from src.gates.repositories import MarketRepository, TrackedInstrument
from src.gates.workflows.portfolio_history_backfill import backfill_portfolio_history
from src.platform_kernel import Money, Quantity, SqliteArtifactStore


def test_backfill_closed_imported_stocks_without_tokens_or_universe_membership(tmp_path):
    db = tmp_path / 'history.db'
    ledger, market = Ledger(db), MarketRepository(db)
    ledger.open_account('account', Money(1000), date(2026, 2, 1))
    market.upsert_instruments([
        TrackedInstrument('priced', 'ABC', 'ABC', 'NSE', '', date(2026, 2, 1)),
        TrackedInstrument('missing', 'UNKNOWN', 'UNKNOWN', 'NSE', '', date(2026, 2, 1)),
    ])
    ledger.record_fills('account', 'trades', 0, [
        Fill('priced', date(2026, 2, 2), FillSide.BUY, Quantity(1), Money(100)),
        Fill('missing', date(2026, 2, 2), FillSide.BUY, Quantity(1), Money(100)),
        Fill('priced', date(2026, 2, 3), FillSide.SELL, Quantity(1), Money(120)),
    ])
    before = ledger.events('account')
    calls = []
    def history(token, start, end, interval):
        calls.append((token, start, end, interval))
        return [{'date': date(2026, 2, 2), 'open': 110, 'high': 110,
                 'low': 110, 'close': 110, 'volume': 10}]
    client = SimpleNamespace(
        instruments=lambda exchange: [{'tradingsymbol': 'ABC', 'instrument_type': 'EQ', 'instrument_token': 42}],
        historical_data=history,
    )
    jobs = SimpleNamespace(_client=lambda: client, repository=market,
                           publisher=ArtifactPublisher(SqliteArtifactStore(db), ArtifactCatalog(db)))
    result = backfill_portfolio_history(ledger, jobs, 'account', date(2026, 2, 4))
    assert result['bar_count'] == 1
    assert result['unavailable_symbols'] == ['UNKNOWN']
    assert calls == [(42, date(2026, 2, 1), date(2026, 2, 4), 'day')]
    assert str(market.bars('priced', date(2026, 2, 1), date(2026, 2, 4))[0]['close']) == '110'
    assert ledger.events('account') == before
    # Repeating the backfill replaces the same dated bars rather than duplicating.
    backfill_portfolio_history(ledger, jobs, 'account', date(2026, 2, 4))
    assert len(market.bars('priced', date(2026, 2, 1), date(2026, 2, 4))) == 1


def test_both_import_routes_schedule_history_after_success():
    from flask import Flask
    from src.gates.http.tradebook import create_tradebook_blueprint
    from src.gates.http.kite_accounts import create_kite_accounts_blueprint
    scheduled = []
    def schedule(account):
        scheduled.append(account)
        return len(scheduled)
    app = Flask(__name__)
    importer = SimpleNamespace(apply=lambda account, body: {'imported_trades': 3})
    sync = SimpleNamespace(import_holdings=lambda *args, **kwargs: {'imported_positions': 2})
    app.register_blueprint(create_tradebook_blueprint(importer, schedule))
    app.register_blueprint(create_kite_accounts_blueprint(None, sync, schedule))
    client = app.test_client()
    response = client.post('/api/portfolio/accounts/account/tradebook/apply', json={})
    assert response.json == {'imported_trades': 3, 'history_backfill_job_id': 1}
    response = client.post('/api/broker-accounts/account/import-holdings', json={'selected_instrument_ids': ['priced']})
    assert response.json == {'imported_positions': 2, 'history_backfill_job_id': 2}
    assert scheduled == ['account', 'account']
    # Invalid import commands never schedule a history update.
    assert client.post('/api/broker-accounts/account/import-holdings', json={'invalid': True}).status_code == 400
    assert len(scheduled) == 2


def test_app_queues_and_worker_executes_history_rebuild(tmp_path, monkeypatch):
    from src.gates import composition
    from src.gates.app import create_app
    class Config:
        TESTING = True
        SECRET_KEY = 'history-test'
        DATA_DIRECTORY = tmp_path
    calls = []
    def rebuild(ledger, jobs, account, as_of, context):
        calls.append((account, as_of))
        return {'bar_count': 10, 'unavailable_symbols': []}
    monkeypatch.setattr(composition, 'backfill_portfolio_history', rebuild)
    app = create_app(Config)
    services = app.extensions['screener_services']
    services.ledger.open_account('account', Money(1000), date(2026, 2, 1))
    response = app.test_client().post('/api/portfolio/accounts/account/valuation/history/backfill', json={'as_of_date': '2026-02-04'})
    assert response.status_code == 200
    job_id = response.json['history_backfill_job_id']
    assert services.jobs.get(job_id).kind == 'portfolio.backfill-price-history'
    services.worker.run_once()
    job = services.jobs.get(job_id)
    assert job.status.value == 'SUCCEEDED'
    assert job.result['bar_count'] == 10
    assert calls == [('account', date(2026, 2, 4))]
