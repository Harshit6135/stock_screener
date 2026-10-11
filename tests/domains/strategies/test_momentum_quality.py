from src.domains.strategies.momentum_quality import (
    _goldilocks,
    _percent_b_score,
    _rsi_regime,
)


def test_goldilocks_score_is_bounded_and_prefers_moderate_positive_distance():
    assert _goldilocks(-1) == 0
    assert _goldilocks(35) == 100
    assert _goldilocks(100) == 0
    assert 0 <= _goldilocks(20) <= 100


def test_rsi_regime_score_rewards_strength_without_overbought_spike():
    assert _rsi_regime(39) == 0
    assert _rsi_regime(70) == 100
    assert _rsi_regime(100) == 60
    assert _rsi_regime(60) > _rsi_regime(50)


def test_percent_b_score_is_bounded_across_price_band_positions():
    assert _percent_b_score(0.4) == 20
    assert _percent_b_score(1.1) == 100
    assert _percent_b_score(3) == 70
    assert all(0 <= _percent_b_score(value) <= 100 for value in (-1, 0.5, 0.7, 1.1, 3))
