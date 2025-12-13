def percentile_rank(self, series: pd.Series) -> pd.Series:
        """
        Calculate percentile rank (0-100) for a series
        Non-parametric normalization robust to outliers
        
        Formula: P_rank = (C_below + 0.5 * C_equal) / N * 100
        """
        return series.rank(pct=True) * 100
    
def z_score_normalize(self, series: pd.Series, 
                        cap_at: float = 3.0) -> pd.Series:
    """
    Z-Score normalization with winsorization
    Maps to 0-100 scale: Score = 50 + (Z * 16.66)
    """
    z_scores = stats.zscore(series, nan_policy='omit')
    z_scores = np.clip(z_scores, -cap_at, cap_at)
    normalized = 50 + (z_scores * 16.66)
    return pd.Series(np.clip(normalized, 0, 100), index=series.index)

def percentile_rank(self, series: pd.Series) -> pd.Series:
        """
        Calculate percentile rank (0-100) for a series
        Non-parametric normalization robust to outliers
        """
        return series.rank(pct=True) * 100
    
def z_score_normalize(self, series: pd.Series, 
                        cap_at: float = 3.0) -> pd.Series:
    """
    Z-Score normalization with winsorization
    Maps to 0-100 scale: Score = 50 + (Z * 16.66)
    """
    z_scores = stats.zscore(series, nan_policy='omit')
    z_scores = np.clip(z_scores, -cap_at, cap_at)
    normalized = 50 + (z_scores * 16.66)
    return pd.Series(np.clip(normalized, 0, 100), index=series.index)

def percentile_rank(series):
    """Calculate percentile rank (0-100) for a series"""
    return series.rank(pct=True) * 100

def z_score_to_scale(series, cap=3):
    """Convert Z-scores to 0-100 scale with capping"""
    z_scores = (series - series.mean()) / series.std()
    z_scores = z_scores.clip(-cap, cap)
    scaled = 50 + (z_scores * 16.66)
    return scaled.clip(0, 100)



# ==========================================
# 2. RANKING ENGINE WITH PROPER NORMALIZATION
# ==========================================
def percentile_rank(series):
    """Calculate percentile rank (0-100) for a series"""
    return series.rank(pct=True) * 100

def z_score_to_scale(series, cap=3):
    """Convert Z-scores to 0-100 scale with capping"""
    z_scores = (series - series.mean()) / series.std()
    z_scores = z_scores.clip(-cap, cap)
    scaled = 50 + (z_scores * 16.66)
    return scaled.clip(0, 100)