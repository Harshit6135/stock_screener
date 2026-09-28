import hashlib
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

# Historical Strategy 3 coverage is retained for the retirement audit only.
pytestmark = pytest.mark.skip(reason="Strategy 3 is retired; Task 4.3 remains incomplete until runtime source is removed")

from src.application.catalog import ArtifactCatalog
from src.application.early_momentum import EarlyMomentumJobs, digest, rank_day, summarize
from src.application.early_momentum_rules import DEFAULT_RULES, parse_rules
from src.application.publication import ArtifactPublisher
from src.platform_kernel import ArtifactStore, DomainValidationError


def _values():
    return {str(i): {
        'symbol': str(i), 'nominal_close': 100, 'residual_score': 10 - i,
        'trend_ok': True, 'bbw_percentile_126': .2, 'cross_ok': True,
        'relative_volume_50': 2, 'extension_atr': 1, 'high': 110, 'low': 90,
        'close': 108, 'atr14_wilder': 5, 'close_location': .9, 'signal_reason_codes': [],
        'naive_52w_high_cross_ok': False,
    } for i in range(10)}


def _jobs(tmp_path, histories):
    database = tmp_path / 'system.db'
    market = SimpleNamespace(
        path=database,
        histories=histories,
        instrument=lambda _: {'instrument_id': 'index'},
    )
    publisher = ArtifactPublisher(ArtifactStore(tmp_path / 'artifacts'), ArtifactCatalog(database))
    jobs = EarlyMomentumJobs(market, publisher, None)
    jobs._source = lambda start, end: (histories(start - timedelta(days=900), end), {}, 'index')
    return jobs, SimpleNamespace(checkpoint=lambda **_: None)


def _publish_raw(jobs, rows, histories, facts=None):
    start, end = date(2024, 12, 31), date(2024, 12, 31)
    feature_path = Path(__file__).parents[1] / 'src/indicators/custom/early_momentum.py'
    jobs._publish('indicators', start, end, {
        'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'namespace': jobs.NAMESPACE, 'indicator_set': jobs.INDICATOR_SET,
        'indicator_feature_hash': digest(feature_path.read_text(encoding='utf-8')),
        'universe_csv_sha256': hashlib.sha256(jobs.universe_csv_path.read_bytes()).hexdigest(),
        'source_hash': digest([histories, facts or {}]), 'rows': rows, 'limitations': [],
    })


def _history_source():
    bars = [
        {'as_of_date': '2024-12-30', 'open': 99, 'high': 101, 'low': 98, 'close': 100, 'volume': 1000},
        {'as_of_date': '2024-12-31', 'open': 100, 'high': 102, 'low': 99, 'close': 101, 'volume': 1000},
        {'as_of_date': '2025-01-02', 'open': 101, 'high': 103, 'low': 100, 'close': 102, 'volume': 1000},
    ]
    identities = {
        'index': {'symbol': 'NIFTY 50', 'exchange': 'NSE', 'isin': 'INDEX:N50'},
        **{str(i): {'symbol': str(i), 'exchange': 'NSE', 'isin': str(i)} for i in range(10)},
    }
    complete = {key: (list(bars), identity) for key, identity in identities.items()}

    def histories(start, end):
        return {
            key: ([bar for bar in series if start.isoformat() <= bar['as_of_date'] <= end.isoformat()], identity)
            for key, (series, identity) in complete.items()
        }

    return complete, histories


def test_default_rule_spec_is_explicit_serializable_and_preserves_legacy_selection():
    assert parse_rules(DEFAULT_RULES.to_dict()) == DEFAULT_RULES
    assert rank_day(_values()) == rank_day(_values(), DEFAULT_RULES.to_dict())


def test_rule_only_changes_recompute_selection_from_cached_values():
    values = _values()
    assert sum(row['raw_signal'] for row in rank_day(values).values()) == 2
    rules = {**DEFAULT_RULES.to_dict(), 'residual_top_fraction': .5, 'volume_minimum': 1.9}
    assert sum(row['raw_signal'] for row in rank_day(values, rules).values()) == 5


@pytest.mark.parametrize(('field', 'value', 'missing'), [
    ('squeeze_mode', 'prior10_minimum', 'bbw_prior10_min_percentile'),
    ('trigger', 'prior20_high_cross', 'prior20_high'),
    ('max_daily_move_atr', 2.0, 'daily_move_atr'),
])
def test_new_causal_features_require_raw_inputs(field, value, missing):
    rules = {**DEFAULT_RULES.to_dict(), field: value}
    with pytest.raises(DomainValidationError, match=missing):
        rank_day(_values(), rules)


def test_close_location_rule_uses_same_day_ohlc():
    rules = {**DEFAULT_RULES.to_dict(), 'close_location_minimum': .95}
    assert not any(row['raw_signal'] for row in rank_day(_values(), rules).values())


def test_optional_rule_checks_finish_the_signal_funnel():
    values = _values()
    values['0']['close_location'] = .5
    values['1']['daily_move_atr'] = 3
    values['2']['benchmark_regime_ok'] = False
    for item in values.values():
        item.setdefault('daily_move_atr', 1)
        item.setdefault('benchmark_regime_ok', True)
    rules = {**DEFAULT_RULES.to_dict(), 'residual_top_fraction': .5,
             'close_location_minimum': .75, 'max_daily_move_atr': 2,
             'benchmark_regime_required': True}
    rows = list(rank_day(values, rules).values())
    events = [{'execution_status': 'unexecutable_missing_open', 'symbol': row['symbol']}
              for row in rows if row['raw_signal']]
    report = summarize(events, rows, rules)
    funnel = report['signal_funnel']
    assert funnel['extension_ok'] == 5
    assert funnel['close_location_ok'] == 4
    assert funnel['daily_move_atr_ok'] == 3
    assert funnel['benchmark_regime_ok'] == 2
    assert funnel['benchmark_regime_ok'] == report['raw_signal_count'] == sum(row['raw_signal'] for row in rows)


@pytest.mark.parametrize(('required', 'expected'), [(False, 5), (True, 4)])
def test_raw_benchmark_value_only_filters_when_rule_is_active(required, expected):
    values = _values()
    for item in values.values():
        item['benchmark_regime_ok'] = True
    values['0']['benchmark_regime_ok'] = False
    rules = {**DEFAULT_RULES.to_dict(), 'residual_top_fraction': .5,
             'benchmark_regime_required': required}
    rows = list(rank_day(values, rules).values())
    events = [{'execution_status': 'unexecutable_missing_open', 'symbol': row['symbol']}
              for row in rows if row['raw_signal']]
    summary = summarize(events, rows, rules)

    assert rows[0]['benchmark_regime_ok'] is False
    assert summary['raw_signal_count'] == expected
    assert list(summary['signal_funnel'].values())[-1] == expected
    assert ('benchmark_regime_ok' in summary['signal_funnel']) is required


@pytest.mark.parametrize('bad', [None, True, '0.2', float('nan'), float('inf')])
def test_rule_numbers_reject_non_json_or_nonfinite_values(bad):
    with pytest.raises(DomainValidationError, match='finite JSON number'):
        parse_rules({**DEFAULT_RULES.to_dict(), 'residual_top_fraction': bad})


@pytest.mark.parametrize('bad', [True, '1', 3])
def test_rule_version_requires_supported_integer(bad):
    with pytest.raises(DomainValidationError, match='version'):
        parse_rules({**DEFAULT_RULES.to_dict(), 'version': bad})


def test_explicit_rule_rerank_is_cache_only_and_persists_hash(tmp_path):
    def forbidden_histories(*_):
        raise AssertionError('ranking must not access market history')

    jobs, context = _jobs(tmp_path, forbidden_histories)
    rows = {key: {'2024-12-31': value} for key, value in _values().items()}
    _publish_raw(jobs, rows, {})
    rules = {**DEFAULT_RULES.to_dict(), 'residual_top_fraction': .5}
    result = jobs.rebuild_rankings({
        'start_date': '2024-12-31', 'end_date': '2024-12-31', 'rules': rules,
    }, context)
    _, stored = jobs.publisher.store.read_json('research/strategy3-rankings', result['artifact_id'])
    assert stored['rules'] == rules
    assert stored['rules_hash'] == digest(rules)
    assert sum(row['raw_signal'] for row in stored['rows']['2024-12-31'].values()) == 5


def test_event_roundtrips_rank_rules_and_development_cutoff_blocks_future_labels(tmp_path):
    complete, histories = _history_source()
    jobs, context = _jobs(tmp_path, histories)
    rows = {key: {'2024-12-31': value} for key, value in _values().items()}
    signal_histories = {
        key: ([bar for bar in bars if bar['as_of_date'] <= '2024-12-31'], identity)
        for key, (bars, identity) in complete.items()
    }
    _publish_raw(jobs, rows, signal_histories)
    rules = {**DEFAULT_RULES.to_dict(), 'residual_top_fraction': .5}
    jobs.rebuild_rankings({
        'start_date': '2024-12-31', 'end_date': '2024-12-31', 'rules': rules,
    }, context)
    result = jobs.event_study({
        'start_date': '2024-12-31', 'end_date': '2024-12-31',
        'evaluation_end_date': '2024-12-31',
    }, context)
    _, report = jobs.publisher.store.read_json('research/strategy3-event-study', result['artifact_id'])
    assert report['rules'] == rules
    assert report['rules_hash'] == digest(rules)
    assert report['outcome_cutoff_date'] == '2024-12-31'
    assert report['summary']['raw_signal_count'] == 5
    assert all('return_20' not in event for event in report['events'])


@pytest.mark.parametrize(('required', 'expected'), [(False, 5), (True, 4)])
def test_event_funnel_uses_stored_rules_with_raw_benchmark_value(tmp_path, required, expected):
    complete, histories = _history_source()
    jobs, context = _jobs(tmp_path, histories)
    values = _values()
    for item in values.values():
        item['benchmark_regime_ok'] = True
    values['0']['benchmark_regime_ok'] = False
    rows = {key: {'2024-12-31': value} for key, value in values.items()}
    signal_histories = {
        key: ([bar for bar in bars if bar['as_of_date'] <= '2024-12-31'], identity)
        for key, (bars, identity) in complete.items()
    }
    _publish_raw(jobs, rows, signal_histories)
    rules = {**DEFAULT_RULES.to_dict(), 'residual_top_fraction': .5,
             'benchmark_regime_required': required}
    jobs.rebuild_rankings({'start_date': '2024-12-31', 'end_date': '2024-12-31',
                           'rules': rules}, context)
    result = jobs.event_study({'start_date': '2024-12-31', 'end_date': '2024-12-31',
                               'evaluation_end_date': '2024-12-31'}, context)

    for summary in (result['summary'], result['yearly']['2024']['strategy']):
        assert summary['raw_signal_count'] == expected
        assert list(summary['signal_funnel'].values())[-1] == expected
        assert ('benchmark_regime_ok' in summary['signal_funnel']) is required


def test_event_rejects_rankings_with_mismatched_rules_hash(tmp_path):
    complete, histories = _history_source()
    jobs, context = _jobs(tmp_path, histories)
    rows = {key: {'2024-12-31': value} for key, value in _values().items()}
    signal_histories = {
        key: ([bar for bar in bars if bar['as_of_date'] <= '2024-12-31'], identity)
        for key, (bars, identity) in complete.items()
    }
    _publish_raw(jobs, rows, signal_histories)
    jobs.rebuild_rankings({'start_date': '2024-12-31', 'end_date': '2024-12-31'}, context)
    _, ranked = jobs._load('rankings', date(2024, 12, 31), date(2024, 12, 31))
    ranked['rules_hash'] = 'stale-rules-hash'
    jobs._publish('rankings', date(2024, 12, 31), date(2024, 12, 31), ranked)

    with pytest.raises(DomainValidationError, match='invalid rule metadata'):
        jobs.event_study({'start_date': '2024-12-31', 'end_date': '2024-12-31',
                          'evaluation_end_date': '2024-12-31'}, context)


def test_explicit_rules_can_publish_zero_result_event(tmp_path):
    complete, histories = _history_source()
    jobs, context = _jobs(tmp_path, histories)
    rows = {key: {'2024-12-31': value} for key, value in _values().items()}
    signal_histories = {
        key: ([bar for bar in bars if bar['as_of_date'] <= '2024-12-31'], identity)
        for key, (bars, identity) in complete.items()
    }
    _publish_raw(jobs, rows, signal_histories)
    rules = {**DEFAULT_RULES.to_dict(), 'volume_minimum': 99.0}
    jobs.rebuild_rankings({
        'start_date': '2024-12-31', 'end_date': '2024-12-31', 'rules': rules,
    }, context)
    result = jobs.event_study({
        'start_date': '2024-12-31', 'end_date': '2024-12-31',
        'evaluation_end_date': '2024-12-31',
    }, context)
    assert result['summary']['raw_signal_count'] == 0


def test_changed_indicator_feature_hash_rejects_cached_raw(tmp_path):
    jobs, context = _jobs(tmp_path, lambda *_: {})
    rows = {key: {'2024-12-31': value} for key, value in _values().items()}
    _publish_raw(jobs, rows, {})
    raw_id, raw = jobs._load('indicators', date(2024, 12, 31), date(2024, 12, 31))
    raw['indicator_feature_hash'] = 'changed-feature-hash'
    replacement = jobs._publish('indicators', date(2024, 12, 31), date(2024, 12, 31), raw)
    assert replacement != raw_id
    with pytest.raises(DomainValidationError, match='feature implementation changed'):
        jobs.rebuild_rankings({'start_date': '2024-12-31', 'end_date': '2024-12-31'}, context)


def test_malformed_real_raw_row_must_not_fail_open():
    malformed = {
        str(i): {
            'symbol': str(i), 'nominal_close': 100, 'residual_score': 10 - i,
            'signal_reason_codes': [],
        }
        for i in range(10)
    }
    with pytest.raises(DomainValidationError, match='raw cache lacks'):
        rank_day(malformed)
