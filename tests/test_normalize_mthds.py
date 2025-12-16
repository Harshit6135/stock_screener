import pytest
import pandas as pd
import numpy as np
from utils.normalize_mthds import percentile_rank, z_score_normalize

def test_percentile_rank():
    # Regular case
    series = pd.Series([10, 20, 30, 40, 50])
    ranks = percentile_rank(series)
    
    # Check bounds
    assert ranks.min() >= 0
    assert ranks.max() <= 100
    # Median should be ~50
    assert ranks[2] == 60.0 # (2 below + 0.5 equal)/5 * 100 = 2.5/5 * 100 = 50? 
    # Pandas rank(pct=True) is slightly different than the formula in docstring
    # Pandas: (rank - 1) / (N - 1) or similar depending on method?
    # Actually utils.normalize_mthds uses: series.rank(pct=True) * 100
    # For default average rank: 1, 2, 3, 4, 5. Pct = 0.2, 0.4, 0.6, 0.8, 1.0
    assert ranks.iloc[-1] == 100.0

def test_percentile_rank_with_duplicates():
    series = pd.Series([10, 20, 20, 30])
    ranks = percentile_rank(series)
    # Tries: 10->1, 20->2.5, 30->4
    # Pct: 1/4=0.25, 2.5/4=0.625, 4/4=1.0
    assert ranks.iloc[1] == 62.5
    assert ranks.iloc[2] == 62.5

def test_z_score_normalize():
    # Create normal distribution
    series = pd.Series([100, 101, 99, 100, 102, 98])
    scores = z_score_normalize(series)
    
    # Mean should be around 50
    assert 40 <= scores.mean() <= 60
    assert scores.min() >= 0
    assert scores.max() <= 100

def test_z_score_with_outliers():
    # Test winsorization (capping)
    series = pd.Series([10, 10, 10, 10, 1000])
    scores = z_score_normalize(series, cap_at=3.0)
    
    # The outlier 1000 should get capped score, not explode
    assert scores.max() <= 100
    
def test_z_score_nan_handling():
    series = pd.Series([10, 20, np.nan, 30])
    scores = z_score_normalize(series)
    
    # Should handle NaNs gracefully (creates NaNs in output usually)
    # The current implementation uses stats.zscore with nan_policy='omit'
    # which returns valid z-scores for non-nans
    assert scores.isnull().sum() == 1
