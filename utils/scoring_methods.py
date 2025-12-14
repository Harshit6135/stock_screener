import pandas as pd


def score_rsi_regime(rsi: pd.Series) -> pd.Series:
        """
        Non-linear RSI scoring for momentum context
        RSI 50-70 is the sweet spot (score 100)
        """
        scores = pd.Series(0.0, index=rsi.index)
        
        scores[rsi < 40] = 0
        scores[(rsi >= 40) & (rsi < 50)] = 25
        scores[(rsi >= 50) & (rsi <= 70)] = 100
        scores[(rsi > 70) & (rsi <= 85)] = 90
        scores[rsi > 85] = 60
        
        return scores
    
def score_trend_extension(dist_200: pd.Series) -> pd.Series:
    """
    Goldilocks curve for distance from 200 EMA
    Zone 1 (0-10%): High score
    Zone 2 (10-40%): Maximum score
    Zone 3 (>50%): Degrades (overextended)
    """
    scores = pd.Series(0.0, index=dist_200.index)
    
    dist_pct = dist_200 * 100
    
    scores[dist_pct < 0] = 0  # Below 200 EMA
    scores[(dist_pct >= 0) & (dist_pct < 10)] = 80
    scores[(dist_pct >= 10) & (dist_pct <= 40)] = 100
    scores[(dist_pct > 40) & (dist_pct <= 50)] = 70
    scores[dist_pct > 50] = 40  # Overextended
    
    return scores
    
def score_percent_b(percent_b: pd.Series) -> pd.Series:
    """
    Score %B position - reward walking the bands
    %B in [0.8, 1.1] = strongest momentum
    """
    scores = pd.Series(0.0, index=percent_b.index)
    
    scores[percent_b < 0.5] = 20
    scores[(percent_b >= 0.5) & (percent_b < 0.8)] = 60
    scores[(percent_b >= 0.8) & (percent_b <= 1.1)] = 100
    scores[percent_b > 1.1] = 80
    
    return scores
