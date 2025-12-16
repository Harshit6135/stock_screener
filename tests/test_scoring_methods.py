import pytest
import pandas as pd
import numpy as np
from utils.scoring_methods import score_rsi_regime, score_trend_extension, score_percent_b

def test_score_rsi_regime():
    # Test cases representing different zones
    rsi_values = pd.Series([30, 45, 60, 80, 90])
    scores = score_rsi_regime(rsi_values)
    
    assert scores[0] == 0    # < 40
    assert scores[1] == 25   # 40-50
    assert scores[2] == 100  # 50-70
    assert scores[3] == 90   # 70-85
    assert scores[4] == 60   # > 85

def test_score_trend_extension():
    # Test cases for extension zones
    # dist_200 is percentage/100, so 0.05 is 5%
    dist_200 = pd.Series([-0.1, 0.05, 0.25, 0.45, 0.60])
    scores = score_trend_extension(dist_200)
    
    assert scores[0] == 0    # < 0
    assert scores[1] == 80   # 0-10%
    assert scores[2] == 100  # 10-40%
    assert scores[3] == 70   # 40-50%
    assert scores[4] == 40   # > 50%

def test_score_percent_b():
    # Test cases for %B zones
    percent_b = pd.Series([0.4, 0.6, 0.9, 1.2])
    scores = score_percent_b(percent_b)
    
    assert scores[0] == 20   # < 0.5
    assert scores[1] == 60   # 0.5-0.8
    assert scores[2] == 100  # 0.8-1.1
    assert scores[3] == 80   # > 1.1

def test_empty_series():
    # Verify handling of empty series
    empty = pd.Series([], dtype=float)
    assert len(score_rsi_regime(empty)) == 0
    assert len(score_trend_extension(empty)) == 0
    assert len(score_percent_b(empty)) == 0
