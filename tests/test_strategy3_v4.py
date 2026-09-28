"""The v4 path must use information available at signal close or next open."""

import pytest

from src.application.early_momentum import (
    evaluate_event,
    rank_day,
    size_v4_position,
    validation_success,
)
from src.application.early_momentum_rules import V4_RULES, parse_rules
from src.platform_kernel import DomainValidationError


def _item(symbol, score):
    return {'symbol': symbol, 'residual_score': score, 'relative_volume_50': 2.0,
            'bbw_prior_percentile_126': .20, 'bbw_percentile_126': .80,
            'prior20_volume': 900, 'prior252_volume': 1000, 'adv30_value': 150_000_000,
            'lower_bb20_2': 90, 'cross_ok': True, 'naive_52w_high_cross_ok': False}


def test_v4_rank_uses_prior_session_squeeze_and_prior_volume():
    values = {str(i): _item(str(i), 10 - i) for i in range(10)}
    values['0']['prior20_volume'] = 1100
    result = rank_day(values, V4_RULES)
    assert not result['0']['raw_signal']
    assert result['0']['signal_reason_codes'] == ['low_volume_ok']
    assert result['1']['raw_signal']
    values['1']['bbw_prior_percentile_126'] = .30
    assert not rank_day(values, V4_RULES)['1']['raw_signal']


def test_v4_next_open_stop_gap_cost_and_sizing():
    item = _item('A', 1)
    bars = {'2024-01-05': {'close': 100},
            '2024-01-08': {'open': 95, 'close': 101, 'low': 94, 'high': 103}}
    event = evaluate_event('2024-01-05', item, bars, list(bars), V4_RULES)
    assert event['execution_status'] == 'executed'
    assert event['initial_stop'] == 90
    assert event['risk_and_name_cap_weight'] == pytest.approx(.1)
    assert event['order_value_limit_inr'] == 1_500_000
    assert event['net_return_1'] == pytest.approx(101 / 95 - 1 - .005)
    bars['2024-01-08']['open'] = 90
    assert evaluate_event('2024-01-05', item, bars, list(bars), V4_RULES)['execution_status'] == 'below_stop_skipped'


def test_v4_stop_exit_and_order_caps():
    item = _item('A', 1)
    bars = {'2024-01-05': {'close': 100},
            '2024-01-08': {'open': 95, 'close': 101, 'low': 89, 'high': 103}}
    event = evaluate_event('2024-01-05', item, bars, list(bars), V4_RULES)
    assert event['return_1'] == pytest.approx(101 / 95 - 1)
    assert event['net_return_1'] == pytest.approx(90 / 95 - 1 - .005)
    order = size_v4_position(10_000_000, 10_000_000, 95, 90, 150_000_000)
    assert order['order_value'] <= 1_000_000
    assert order['nominal_risk'] <= 100_000
    assert order['shares'] == 10_526


def test_validation_success_requires_both_years_and_all_gates():
    def summary(net, mae, fail):
        return {'horizons': {'20': {'net_return': {'count': 30, 'mean': net}},
                             '5': {'mae': {'p90': mae}, 'failed_breakout_rate': fail}}}
    yearly = {str(year): {'strategy': summary(.02, .04, .3),
                          'baseline': summary(.01, .05, .4)} for year in (2024, 2025)}
    assert validation_success(yearly)['passed']
    yearly['2025']['strategy']['horizons']['20']['net_return']['count'] = 29
    assert not validation_success(yearly)['passed']


def test_v4_rules_require_all_v4_filters():
    assert parse_rules(V4_RULES).version == 2
    with pytest.raises(DomainValidationError, match='version 2'):
        parse_rules({'version': 2})
