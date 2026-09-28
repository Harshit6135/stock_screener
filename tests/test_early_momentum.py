from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.application.early_momentum import adjust_bars, evaluate_event, rank_day, summarize
from src.indicators.custom.early_momentum import early_momentum_feature_series


def _bars(count: int, *, scale: float = 1.0) -> list[dict[str, object]]:
    start = date(2024, 1, 1)
    close = 100.0 * scale
    result = []
    for offset in range(count):
        # Deterministic variation gives residual volatility while preserving
        # positive, complete OHLCV inputs.
        close *= 1.001 + ((offset % 7) - 3) * 0.0002 * scale
        result.append({
            "as_of_date": (start + timedelta(days=offset)).isoformat(),
            "open": close * 0.998, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": 1_000_000 + offset * 100,
        })
    return result


def test_early_momentum_requires_317_bars_and_exposes_raw_score():
    benchmark = _bars(318)
    assert early_momentum_feature_series(_bars(316, scale=1.03), benchmark) == {}

    values = early_momentum_feature_series(_bars(318, scale=1.03), benchmark)
    assert len(values) == 2
    latest = values["2024-11-13"]
    assert isinstance(latest["residual_score"], float)
    assert "residual_rank" not in latest  # Ranking is a separate cache stage.
    assert latest["bbw_percentile_126"] <= 1


def test_first_day_excludes_following_crash_and_missing_session_expires():
    bars = {'2024-01-05': {'close': 100},
            '2024-01-08': {'open': 100, 'close': 101, 'low': 99, 'high': 102},
            '2024-01-09': {'open': 80, 'close': 80, 'low': 75, 'high': 85}}
    sessions = list(bars)
    event = evaluate_event('2024-01-05', {'symbol': 'A'}, bars, sessions)
    assert event['return_1'] == pytest.approx(.01)
    assert event['mae_1'] == pytest.approx(.01)
    assert event['mae_2'] == pytest.approx(.25)
    assert event['h5_status'] == 'insufficient_future_data'
    del bars['2024-01-08']
    assert evaluate_event('2024-01-05', {'symbol': 'A'}, bars, sessions)['execution_status'] == 'unexecutable_missing_open'


@pytest.mark.parametrize(('opening', 'status'), [(103, 'executed'), (103.001, 'gap_skipped')])
def test_gap_boundary(opening, status):
    bars = {'2024-01-05': {'close': 100},
            '2024-01-08': {'open': opening, 'close': 104, 'low': 100, 'high': 105}}
    assert evaluate_event('2024-01-05', {'symbol': 'A'}, bars, list(bars))['execution_status'] == status


def test_rank_requires_price_and_positive_strength_and_deterministic_ties():
    values = {str(i): {'symbol': str(i), 'nominal_close': 100, 'residual_score': -i - 1,
                      'trend_ok': True, 'bbw_percentile_126': .2, 'cross_ok': True,
                      'relative_volume_50': 2, 'extension_atr': 1,
                      'signal_reason_codes': []} for i in range(5)}
    values['penny'] = {**values['0'], 'symbol': 'P', 'nominal_close': 14, 'residual_score': 100}
    ranked = rank_day(values)
    assert not any(row['raw_signal'] for row in ranked.values())
    assert ranked['penny']['residual_rank'] is None
    assert ranked['0']['residual_rank'] == 1
    values['1']['residual_score'] = values['0']['residual_score'] = 3
    assert rank_day(values)['0']['raw_signal']
    assert not rank_day(values)['1']['raw_signal']


def test_split_adjusts_volume_and_preserves_nominal_price():
    bars = [{'as_of_date': '2024-01-05', 'open': 100, 'close': 100, 'high': 102, 'low': 98, 'volume': 1000}]
    action = {'effective_date': '2024-01-08', 'action_type': 'SPLIT', 'ratio': '2'}
    adjusted = adjust_bars(bars, [action], date(2024, 1, 8))[0]
    assert adjusted['close'] == 50
    assert adjusted['volume'] == 2000
    assert adjusted['nominal_close'] == 100
    assert adjust_bars(bars, [action], date(2024, 1, 5))[0]['close'] == 100


def test_report_loss_tail_and_empty_samples():
    events = [{'execution_status': 'executed', 'symbol': 'A', 'mae_1': v}
              for v in [.01, .02, .03, .04, .05, .06, .07, .08, .3, .4]]
    report = summarize(events, [])
    assert report['horizons']['1']['mae']['p90'] == .3
    assert report['horizons']['5']['return']['mean'] is None
    assert report['horizons']['5']['failed_breakout_rate'] is None


def test_prefix_invariance_and_missing_bar_rejection():
    stock, benchmark = _bars(330, scale=1.03), _bars(330)
    first = early_momentum_feature_series(stock[:318], benchmark[:318])
    extended = early_momentum_feature_series(stock, benchmark)
    assert all(extended[day] == values for day, values in first.items())
    assert early_momentum_feature_series(stock[:100] + stock[101:318], benchmark[:318]) == {}


def test_exact_regression_windows_atr_seed_and_prior_only_volume():
    import math

    import numpy as np

    stock, benchmark = _bars(317, scale=1.03), _bars(317)
    for index, bar in enumerate(stock):
        for key in ('open', 'high', 'low', 'close'):
            bar[key] *= 1 + .01 * math.sin(index / 11)
    stock[-1]['volume'] *= 4
    result = list(early_momentum_feature_series(stock, benchmark).values())[-1]
    rs = np.diff(np.log([bar['close'] for bar in stock]))
    rm = np.diff(np.log([bar['close'] for bar in benchmark]))
    _alpha, beta = np.linalg.lstsq(np.column_stack((np.ones(252), rm[:252])), rs[:252], rcond=None)[0]
    residuals = rs[253:] - beta * rm[253:]
    assert len(residuals) == 63
    assert result['residual_score'] == pytest.approx(residuals.sum() / residuals.std(ddof=1), rel=1e-6)
    assert result['relative_volume_50'] == pytest.approx(stock[-1]['volume'] / np.mean([b['volume'] for b in stock[-51:-1]]))
    ranges = [max(b['high'] - b['low'], abs(b['high'] - stock[i-1]['close']), abs(b['low'] - stock[i-1]['close']))
              for i, b in enumerate(stock) if i > 0]
    atr = sum(ranges[:14]) / 14
    for tr in ranges[14:]:
        atr = (13 * atr + tr) / 14
    assert result['atr14_wilder'] == pytest.approx(atr)


def test_stages_are_cache_only_content_addressed_and_reject_stale_sources(tmp_path):
    from types import SimpleNamespace

    from flask import Flask

    from src.application.catalog import ArtifactCatalog
    from src.application.early_momentum import EarlyMomentumJobs
    from src.application.early_momentum_web import create_early_momentum_blueprint
    from src.application.publication import ArtifactPublisher
    from src.platform_kernel import ArtifactStore, DomainValidationError

    database = tmp_path / 'system.db'
    source = {'index': (_bars(345), {'symbol': 'NIFTY 500', 'exchange': 'NSE', 'isin': 'INDEX:N500'})}
    for i in range(5):
        source[str(i)] = (_bars(345, scale=1.01 + i * .01),
                          {'symbol': str(i), 'exchange': 'NSE', 'isin': str(i)})
    source['bse'] = (_bars(345), {'symbol': 'B', 'exchange': 'BSE', 'isin': 'B'})
    calls = []
    def histories(start, end, *, isins=None):
        calls.append((start, end))
        return {key: ([b for b in bars if start.isoformat() <= b['as_of_date'] <= end.isoformat()], identity)
                for key, (bars, identity) in source.items() if isins is None or identity['isin'] in isins}
    market = SimpleNamespace(path=database, histories=histories,
                             instrument=lambda _: {'instrument_id': 'index', 'isin': 'INDEX:N500'})
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / 'artifacts'), ArtifactCatalog(database))
    universe_csv = tmp_path / 'nifty500.csv'
    universe_csv.write_text('Symbol,Series,ISIN Code\n' + ''.join(f'{i},EQ,{i:012d}\n' for i in range(5)) +
                            'B,EQ,00000000000B\n', encoding='utf-8')
    for i in range(5):
        source[str(i)][1]['isin'] = f'{i:012d}'
    source['outside'] = (_bars(345), {'symbol': 'OUTSIDE', 'exchange': 'NSE', 'isin': '999999999999'})
    jobs = EarlyMomentumJobs(market, publisher, None, universe_csv_path=universe_csv)
    context = SimpleNamespace(checkpoint=lambda **_: None)
    payload = {'start_date': '2024-11-12', 'end_date': '2024-11-13'}
    first = jobs.rebuild_indicators(payload, context)
    assert first['rows'] == 10  # BSE and non-constituent NSE stocks are excluded.
    _, raw = publisher.store.read_json('research/strategy3-indicators', first['artifact_id'])
    assert raw['benchmark'] == 'NIFTY 500'
    assert raw['universe_member_count'] == 6
    assert raw['universe_matched_count'] == 5
    assert raw['universe_missing_isins'] == ['00000000000B']
    from src.application.sqlite import sqlite_connection
    with sqlite_connection(database, read_only=True) as connection:
        assert connection.execute('SELECT COUNT(*) FROM nifty500_membership_snapshots').fetchone()[0] == 6
    count = len(calls)
    jobs.rebuild_rankings(payload, context)
    assert len(calls) == count  # Ranking never loads OHLCV.
    report = jobs.event_study(payload, context)
    assert jobs.event_study(payload, context)['artifact_id'] == report['artifact_id']
    app = Flask(__name__)
    app.register_blueprint(create_early_momentum_blueprint(publisher.store))
    assert app.test_client().get('/strategy3/reports/' + report['artifact_id']).status_code == 200
    assert app.test_client().get('/api/v2/strategy3/reports/' + report['artifact_id']).status_code == 200
    source['0'][0][317]['close'] *= 1.001
    with pytest.raises(DomainValidationError, match='source changes'):
        jobs.event_study(payload, context)
    assert jobs.rebuild_indicators(payload, context)['artifact_id'] != first['artifact_id']
    with pytest.raises(DomainValidationError, match='rankings are stale'):
        jobs.event_study(payload, context)
    jobs.rebuild_rankings(payload, context)
    assert jobs.event_study(payload, context)['artifact_id'] != report['artifact_id']
    # A complete empty replacement removes previous eligible rows.
    for key in list(source):
        if key != 'index':
            del source[key]
    assert jobs.rebuild_indicators(payload, context)['rows'] == 0
    jobs.rebuild_rankings(payload, context)
    assert jobs.event_study(payload, context)['summary']['raw_signal_count'] == 0
