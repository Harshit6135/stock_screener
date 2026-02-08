import pandas as pd
from config.strategies_config import PenaltyBoxConfig


def apply_penalty_box(df: pd.DataFrame, 
                      config: PenaltyBoxConfig = None) -> pd.DataFrame:
    """
    Apply penalty box rules - set composite_score=0 for disqualified stocks
    
    Rules:
    1. Price below 200 EMA
    2. ATR spike above threshold
    3. Turnover below minimum
    
    Args:
        df: DataFrame with columns: close, ema_200, atr_spike, avg_turnover_20d, composite_score
        config: PenaltyBoxConfig with thresholds
        
    Returns:
        DataFrame with composite_score set to 0 for penalized stocks
    """
    if config is None:
        config = PenaltyBoxConfig()
    
    df = df.copy()
    mask = pd.Series(False, index=df.index)
    
    # Rule 1: Below 200 EMA
    if config.below_ema_200 and 'ema_200' in df.columns and 'close' in df.columns:
        mask |= (df['close'] < df['ema_200'])
    
    # Rule 2: ATR spike
    if config.atr_spike_threshold and 'atr_spike' in df.columns:
        mask |= (df['atr_spike'] > config.atr_spike_threshold)
    
    # Rule 3: Low turnover
    if config.min_turnover_cr and 'avg_turnover_20d' in df.columns:
        min_turnover = config.min_turnover_cr * 1e7  # CR to absolute
        mask |= (df['avg_turnover_20d'] < min_turnover)
    
    # Apply penalty
    if 'composite_score' in df.columns:
        df.loc[mask, 'composite_score'] = 0
    
    return df


def check_penalty_status(close: float, ema_200: float, atr_spike: float,
                         avg_turnover: float, config: PenaltyBoxConfig = None) -> dict:
    """
    Check penalty box status for a single stock
    
    Returns:
        dict with penalty status and reasons
    """
    if config is None:
        config = PenaltyBoxConfig()
    
    reasons = []
    
    if config.below_ema_200 and close < ema_200:
        reasons.append("below_ema_200")
    
    if config.atr_spike_threshold and atr_spike > config.atr_spike_threshold:
        reasons.append(f"atr_spike>{config.atr_spike_threshold}")
    
    min_turnover = config.min_turnover_cr * 1e7
    if config.min_turnover_cr and avg_turnover < min_turnover:
        reasons.append(f"turnover<{config.min_turnover_cr}Cr")
    
    return {
        "penalized": len(reasons) > 0,
        "reasons": reasons
    }
