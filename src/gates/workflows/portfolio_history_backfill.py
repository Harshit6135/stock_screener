"""Backfill prices for ledger instruments without research-universe restrictions."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException
from requests.exceptions import RequestException

from src.domains.market_data import KiteHistoricalBarsProvider, NormalizedBar
from src.domains.portfolio_accounting.tradebook import canonical_symbol
from src.gates.workflows.market_ingestion import ingest_market_bars
from src.platform_kernel import DomainValidationError
from src.platform_kernel.security import sanitize_error


def backfill_portfolio_history(ledger, jobs, account_id, as_of, context=None):
    account = next((a for a in ledger.accounts() if a['account_id'] == account_id), None)
    if account is None:
        raise DomainValidationError('account not found')
    opened = date.fromisoformat(account['opening_date'])
    if as_of < opened or as_of > datetime.now(ZoneInfo("Asia/Kolkata")).date():
        raise DomainValidationError('history date must be between opening date and today')
    client = jobs._client()
    provider = KiteHistoricalBarsProvider(client)
    # Imported closed trades can have no token and sit outside NIFTY 500.
    # Resolve against the current provider dump; never guess from an old token.
    dump = client.instruments('NSE')
    by_symbol = {}
    for item in dump:
        if item.get('instrument_type') == 'EQ':
            by_symbol.setdefault(canonical_symbol(item['tradingsymbol']), []).append(item)
    instruments = {
        e['event']['instrument_id'] for e in ledger.events(account_id)
        if e['event'].get('instrument_id') and e['occurred_at'][:10] <= as_of.isoformat()
    }
    results = []
    for current, instrument_id in enumerate(sorted(instruments)):
        identity = jobs.repository.instrument_by_id(instrument_id)
        symbol = identity['symbol'] if identity else instrument_id
        if context:
            context.checkpoint(progress={'stage': 'portfolio_prices', 'current': current,
                                         'total': len(instruments), 'message': f'Fetching {symbol}'})
        candidates = by_symbol.get(canonical_symbol(symbol), []) if identity and identity['exchange'] == 'NSE' else []
        if len(candidates) != 1:
            results.append({'symbol': symbol, 'bar_count': 0, 'error': 'No unique current NSE equity token'})
            continue
        token = str(candidates[0]['instrument_token'])
        count, start = 0, opened
        try:
            while start <= as_of:
                end = min(as_of, start + timedelta(days=1999))
                fetched, raw, _quality = provider.get_bars_with_quality(token, start, end)
                bars = tuple(NormalizedBar(
                    instrument_id, b.as_of_date, b.open, b.high, b.low, b.close,
                    b.volume, b.traded_value,
                ) for b in fetched)
                if bars:
                    _, artifact = ingest_market_bars(
                        jobs.publisher, 'kite', bars,
                        source_request={'account_id': account_id, 'symbol': symbol,
                                        'provider_token': token, 'start_date': start.isoformat(),
                                        'end_date': end.isoformat(), 'purpose': 'portfolio_history'},
                        raw_payload=raw, provider_version='kiteconnect-v5',
                    )
                    jobs.repository.upsert_bars(instrument_id, bars, artifact.artifact_id)
                    count += len(bars)
                start = end + timedelta(days=1)
            results.append({'symbol': symbol, 'bar_count': count})
        except (DomainValidationError, KiteException, RequestException) as exc:
            results.append({'symbol': symbol, 'bar_count': count, 'error': sanitize_error(exc)})
    return {'account_id': account_id, 'bar_count': sum(r['bar_count'] for r in results),
            'instruments': results, 'unavailable_symbols': [r['symbol'] for r in results if r.get('error') or not r['bar_count']]}
