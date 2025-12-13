
import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import pandas_ta as ta
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
from scipy import stats

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
from scipy import stats



@dataclass
class ScorecardWeights:
    """Configuration for factor weights in composite score"""
    trend_strength: float = 0.30
    momentum_velocity: float = 0.25
    risk_efficiency: float = 0.20
    conviction: float = 0.15
    structure: float = 0.10


class StockRankingScorecard:
    """
    Multi-Factor Momentum Scorecard for Indian Markets
    Based on quantitative equity ranking framework
    """
    
    def __init__(self, weights: Optional[ScorecardWeights] = None):
        self.weights = weights or ScorecardWeights()

    # ============= COMPOSITE SCORECARD =============
    
    def calculate_composite_score(self, 
                                 stock_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Calculate composite score for multiple stocks
        
        Args:
            stock_data: Dict of {stock_symbol: DataFrame with OHLCV data}
            
        Returns:
            DataFrame with stocks and their factor scores + composite score
        """
        results = []
        
        for symbol, df in stock_data.items():
            try:
                # Calculate all metrics
                metrics = self._calculate_all_metrics(df)
                
                # Get latest values
                latest = {k: v.iloc[-1] if len(v) > 0 else np.nan 
                         for k, v in metrics.items()}
                latest['symbol'] = symbol
                
                results.append(latest)
                
            except Exception as e:
                print(f"Error processing {symbol}: {e}")
                continue
        
        if not results:
            return pd.DataFrame()
        
        metrics_df = pd.DataFrame(results)
        
        # Calculate percentile ranks across universe
        ranked_df = self._calculate_percentile_ranks(metrics_df)
        
        # Calculate composite scores
        ranked_df = self._calculate_weighted_composite(ranked_df)
        
        # Apply penalty box
        ranked_df = self._apply_universe_penalties(stock_data, ranked_df)
        
        # Sort by composite score
        ranked_df = ranked_df.sort_values('composite_score', ascending=False)
        
        return ranked_df
    
    
    
    def _calculate_percentile_ranks(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate percentile ranks across the universe"""
        
        ranked = df.copy()
        
        # Define metrics to rank
        rank_cols = {
            'ema_50_slope': 'trend_rank',
            'ppo': 'momentum_ppo_rank',
            'risk_adj_return': 'efficiency_rank',
            'rvol': 'volume_rank',
            'bb_width': 'structure_rank'
        }
        
        for col, rank_name in rank_cols.items():
            if col in ranked.columns:
                ranked[rank_name] = self.percentile_rank(ranked[col])
        
        # Use pre-scored metrics
        if 'rsi_regime_score' in ranked.columns:
            ranked['momentum_rsi_rank'] = ranked['rsi_regime_score']
        
        if 'trend_extension_score' in ranked.columns:
            ranked['trend_extension_rank'] = ranked['trend_extension_score']
        
        if 'percent_b_score' in ranked.columns:
            ranked['structure_bb_rank'] = ranked['percent_b_score']
        
        return ranked
    
    def _calculate_weighted_composite(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate weighted composite score"""
        
        result = df.copy()
        
        # Aggregate trend (combine EMA slope and extension)
        if 'trend_rank' in result.columns and 'trend_extension_rank' in result.columns:
            result['final_trend_score'] = (
                result['trend_rank'] * 0.6 + 
                result['trend_extension_rank'] * 0.4
            )
        else:
            result['final_trend_score'] = result.get('trend_rank', 0)
        
        # Aggregate momentum (RSI + PPO)
        momentum_cols = [c for c in ['momentum_rsi_rank', 'momentum_ppo_rank'] 
                        if c in result.columns]
        if momentum_cols:
            result['final_momentum_score'] = result[momentum_cols].mean(axis=1)
        else:
            result['final_momentum_score'] = 0
        
        # Calculate composite score
        result['composite_score'] = (
            self.weights.trend_strength * result.get('final_trend_score', 0) +
            self.weights.momentum_velocity * result.get('final_momentum_score', 0) +
            self.weights.risk_efficiency * result.get('efficiency_rank', 0) +
            self.weights.conviction * result.get('volume_rank', 0) +
            self.weights.structure * result.get('structure_rank', 0)
        )
        
        return result
    
    def _apply_universe_penalties(self, 
                                 stock_data: Dict[str, pd.DataFrame],
                                 ranked_df: pd.DataFrame) -> pd.DataFrame:
        """Apply penalty box rules across universe"""
        
        result = ranked_df.copy()
        
        for idx, row in result.iterrows():
            symbol = row['symbol']
            if symbol in stock_data:
                df = stock_data[symbol]
                penalized_score = self.apply_penalty_box(
                    df, 
                    pd.Series([row['composite_score']])
                )
                result.at[idx, 'composite_score'] = penalized_score.iloc[0]
        
        return result
    

    
    def calculate_composite_score(self, 
                                 stock_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Calculate composite score for multiple stocks
        
        Args:
            stock_data: Dict of {stock_symbol: DataFrame with OHLCV data}
            
        Returns:
            DataFrame with stocks and their factor scores + composite score
        """
        results = []
        
        for symbol, df in stock_data.items():
            try:
                # Calculate all metrics
                metrics = self._calculate_all_metrics(df)
                
                # Get latest values
                latest = {k: v.iloc[-1] if len(v) > 0 else np.nan 
                         for k, v in metrics.items()}
                latest['symbol'] = symbol
                
                results.append(latest)
                
            except Exception as e:
                print(f"Error processing {symbol}: {e}")
                continue
        
        if not results:
            return pd.DataFrame()
        
        metrics_df = pd.DataFrame(results)
        
        # Calculate percentile ranks across universe
        ranked_df = self._calculate_percentile_ranks(metrics_df)
        
        # Calculate composite scores
        ranked_df = self._calculate_weighted_composite(ranked_df)
        
        # Apply penalty box
        ranked_df = self._apply_universe_penalties(stock_data, ranked_df)
        
        # Sort by composite score
        ranked_df = ranked_df.sort_values('composite_score', ascending=False)
        
        return ranked_df
    
    
    
    def _calculate_percentile_ranks(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate percentile ranks across the universe"""
        
        ranked = df.copy()
        
        # Define metrics to rank
        rank_cols = {
            'ema_50_slope': 'trend_rank',
            'ppo': 'momentum_ppo_rank',
            'risk_adj_return': 'efficiency_rank',
            'rvol': 'volume_rank',
            'bb_width': 'structure_rank'
        }
        
        for col, rank_name in rank_cols.items():
            if col in ranked.columns:
                ranked[rank_name] = self.percentile_rank(ranked[col])
        
        # Use pre-scored metrics
        if 'rsi_regime_score' in ranked.columns:
            ranked['momentum_rsi_rank'] = ranked['rsi_regime_score']
        
        if 'trend_extension_score' in ranked.columns:
            ranked['trend_extension_rank'] = ranked['trend_extension_score']
        
        if 'percent_b_score' in ranked.columns:
            ranked['structure_bb_rank'] = ranked['percent_b_score']
        
        return ranked
    
    def _calculate_weighted_composite(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate weighted composite score"""
        
        result = df.copy()
        
        # Aggregate trend (combine EMA slope and extension)
        if 'trend_rank' in result.columns and 'trend_extension_rank' in result.columns:
            result['final_trend_score'] = (
                result['trend_rank'] * 0.6 + 
                result['trend_extension_rank'] * 0.4
            )
        else:
            result['final_trend_score'] = result.get('trend_rank', 0)
        
        # Aggregate momentum (RSI + PPO)
        momentum_cols = [c for c in ['momentum_rsi_rank', 'momentum_ppo_rank'] 
                        if c in result.columns]
        if momentum_cols:
            result['final_momentum_score'] = result[momentum_cols].mean(axis=1)
        else:
            result['final_momentum_score'] = 0
        
        # Calculate composite score
        result['composite_score'] = (
            self.weights.trend_strength * result.get('final_trend_score', 0) +
            self.weights.momentum_velocity * result.get('final_momentum_score', 0) +
            self.weights.risk_efficiency * result.get('efficiency_rank', 0) +
            self.weights.conviction * result.get('volume_rank', 0) +
            self.weights.structure * result.get('structure_rank', 0)
        )
        
        return result
    
    def _apply_universe_penalties(self, 
                                 stock_data: Dict[str, pd.DataFrame],
                                 ranked_df: pd.DataFrame) -> pd.DataFrame:
        """Apply penalty box rules across universe"""
        
        result = ranked_df.copy()
        
        for idx, row in result.iterrows():
            symbol = row['symbol']
            if symbol in stock_data:
                df = stock_data[symbol]
                penalized_score = self.apply_penalty_box(
                    df, 
                    pd.Series([row['composite_score']])
                )
                result.at[idx, 'composite_score'] = penalized_score.iloc[0]
        
        return result
    
    # ============= PORTFOLIO MANAGEMENT =============
    



CONFIG = {
    'LOOKBACK_DAYS': 365,
    'Weights': {
        'Trend': 0.30,      # EMA Slope & Distance
        'Momentum': 0.25,   # RSI & PPO
        'Risk': 0.20,       # ROC/ATR Efficiency
        'Volume': 0.15,     # Relative Volume
        'Structure': 0.10   # Bollinger Band Width
    },
    'Switch_Buffer': 0.25,  # New stock must be 25% better to switch
    'Degradation_Threshold': 50,  # Exit if score drops below this
    'Capital': 100000,
    'Risk_Per_Trade': 0.02,
    'Min_Turnover_Cr': 5,  # Minimum daily turnover in Crores
    'Min_Price': 50
}



def build_scorecard(tickers):
    """Build complete ranking scorecard with normalization"""
    print("Fetching data and calculating indicators...")
    data_list = []
    
    for t in tickers:
        row = fetch_and_calculate(t)
        if row is not None:
            row['Ticker'] = t
            data_list.append(row)
    
    if len(data_list) == 0:
        print("No valid data retrieved!")
        return pd.DataFrame()
    
    score_df = pd.DataFrame(data_list).set_index('Ticker')
    
    print(f"\nProcessing {len(score_df)} stocks...")
    
    # --- COMPONENT SCORING ---
    
    # 1. TREND SCORE (30%)
    # Combine EMA slope and distance with appropriate weighting
    trend_slope_rank = percentile_rank(score_df['EMA_50_Slope'])
    
    # Non-linear scoring for distance (Goldilocks zone)
    def goldilocks_dist(dist):
        if pd.isna(dist) or dist < 0:
            return 0
        elif dist < 0.10:
            return 70
        elif dist < 0.40:
            return 100
        elif dist < 0.50:
            return 80
        else:
            return 40  # Overextended
    
    dist_score = score_df['Dist_200'].apply(goldilocks_dist)
    
    score_df['Trend_Rank'] = (trend_slope_rank * 0.5 + dist_score * 0.5)
    
    # 2. MOMENTUM SCORE (25%)
    rsi_score = rsi_regime_score(score_df['RSI_Smooth'])
    ppo_rank = percentile_rank(score_df['PPO'])
    ppo_hist_rank = percentile_rank(score_df['PPO_Hist_Slope'])
    
    score_df['Momentum_Rank'] = (rsi_score * 0.5 + ppo_rank * 0.3 + ppo_hist_rank * 0.2)
    
    # 3. RISK/EFFICIENCY SCORE (20%)
    # Use the 6-month efficiency as primary metric
    score_df['Risk_Rank'] = percentile_rank(score_df['Efficiency_6M'])
    
    # 4. VOLUME SCORE (15%)
    rvol_rank = percentile_rank(score_df['RVOL'])
    corr_rank = percentile_rank(score_df['Vol_Price_Corr'])
    score_df['Volume_Rank'] = (rvol_rank * 0.7 + corr_rank * 0.3)
    
    # 5. STRUCTURE SCORE (10%)
    bb_width_rank = percentile_rank(score_df['BB_Width_ROC'])
    bb_percentb_rank = percentile_rank(score_df['BB_PercentB'])
    score_df['Structure_Rank'] = (bb_width_rank * 0.6 + bb_percentb_rank * 0.4)
    
    # --- COMPOSITE SCORE CALCULATION ---
    score_df['Final_Score'] = (
        (score_df['Trend_Rank'] * CONFIG['Weights']['Trend']) +
        (score_df['Momentum_Rank'] * CONFIG['Weights']['Momentum']) +
        (score_df['Risk_Rank'] * CONFIG['Weights']['Risk']) +
        (score_df['Volume_Rank'] * CONFIG['Weights']['Volume']) +
        (score_df['Structure_Rank'] * CONFIG['Weights']['Structure'])
    )
    
    # --- PENALTY BOX (HARD FILTERS) ---
    # Set score to 0 for disqualified stocks
    penalty_mask = (
        score_df['Broken_Trend'] |
        score_df['ATR_Spike'] |
        (score_df['Avg_Turnover_Cr'] < CONFIG['Min_Turnover_Cr']) |
        (score_df['Close'] < CONFIG['Min_Price']) |
        (~score_df['Golden_Cross'].astype(bool))
    )
    
    score_df.loc[penalty_mask, 'Final_Score'] = 0
    
    return score_df.sort_values(by='Final_Score', ascending=False)



# ==========================================
# CONFIGURATION & UNIVERSE
# ==========================================
TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "HINDUNILVR.NS",
    "ICICIBANK.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS", "ITC.NS"
]

CONFIG = {
    'LOOKBACK_DAYS': 365,
    'Weights': {
        'Trend': 0.30,      # EMA Slope & Distance
        'Momentum': 0.25,   # RSI & PPO
        'Risk': 0.20,       # ROC/ATR Efficiency
        'Volume': 0.15,     # Relative Volume
        'Structure': 0.10   # Bollinger Band Width
    },
    'Switch_Buffer': 0.25,  # New stock must be 25% better to switch
    'Degradation_Threshold': 50,  # Exit if score drops below this
    'Capital': 100000,
    'Risk_Per_Trade': 0.02,
    'Min_Turnover_Cr': 5,  # Minimum daily turnover in Crores
    'Min_Price': 50
}




def build_scorecard(tickers):
    """Build complete ranking scorecard with normalization"""
    print("Fetching data and calculating indicators...")
    data_list = []
    
    for t in tickers:
        row = fetch_and_calculate(t)
        if row is not None:
            row['Ticker'] = t
            data_list.append(row)
    
    if len(data_list) == 0:
        print("No valid data retrieved!")
        return pd.DataFrame()
    
    score_df = pd.DataFrame(data_list).set_index('Ticker')
    
    print(f"\nProcessing {len(score_df)} stocks...")
    
    # --- COMPONENT SCORING ---
    
    # 1. TREND SCORE (30%)
    # Combine EMA slope and distance with appropriate weighting
    trend_slope_rank = percentile_rank(score_df['EMA_50_Slope'])
    
    # Use Z-Score for 200 EMA distance to measure statistical significance
    # Per PDF Section 3.2.2: "A stock at +25% above 200 EMA with Z=+2.0 indicates
    # statistically significant trend strength"
    dist_z_score = z_score_to_scale(score_df['Dist_200'])
    
    # Apply Goldilocks penalty for overextension (Z > 2.5)
    def goldilocks_penalty(z_score, dist):
        if pd.isna(dist) or dist < 0:
            return 0
        # Penalize Z-scores > 2.5 (overextended per PDF Section 3.2.2)
        if z_score > 75:  # Equivalent to Z > 2.5
            return z_score * 0.6  # 40% penalty
        return z_score
    
    dist_score = score_df.apply(lambda row: goldilocks_penalty(
        z_score_to_scale(pd.Series([row['Dist_200']])).iloc[0] 
        if not pd.isna(row['Dist_200']) else 0,
        row['Dist_200']
    ), axis=1)
    
    score_df['Trend_Rank'] = (trend_slope_rank * 0.5 + dist_score * 0.5)
    
    # 2. MOMENTUM SCORE (25%)
    rsi_score = rsi_regime_score(score_df['RSI_Smooth'])
    ppo_rank = percentile_rank(score_df['PPO'])
    ppo_hist_rank = percentile_rank(score_df['PPO_Hist_Slope'])
    
    score_df['Momentum_Rank'] = (rsi_score * 0.5 + ppo_rank * 0.3 + ppo_hist_rank * 0.2)
    
    # 3. RISK/EFFICIENCY SCORE (20%)
    # Use the 6-month efficiency as primary metric
    score_df['Risk_Rank'] = percentile_rank(score_df['Efficiency_6M'])
    
    # 4. VOLUME SCORE (15%)
    rvol_rank = percentile_rank(score_df['RVOL'])
    corr_rank = percentile_rank(score_df['Vol_Price_Corr'])
    score_df['Volume_Rank'] = (rvol_rank * 0.7 + corr_rank * 0.3)
    
    # 5. STRUCTURE SCORE (10%)
    # Use Z-Score for BB Width to measure "abnormality" per PDF Section 2.2
    # "Z-Scores are particularly valuable for measuring abnormality in volatility"
    bb_width_z_score = z_score_to_scale(score_df['BB_Width_ROC'])
    bb_percentb_rank = percentile_rank(score_df['BB_PercentB'])
    score_df['Structure_Rank'] = (bb_width_z_score * 0.6 + bb_percentb_rank * 0.4)
    
    # --- COMPOSITE SCORE CALCULATION ---
    score_df['Final_Score'] = (
        (score_df['Trend_Rank'] * CONFIG['Weights']['Trend']) +
        (score_df['Momentum_Rank'] * CONFIG['Weights']['Momentum']) +
        (score_df['Risk_Rank'] * CONFIG['Weights']['Risk']) +
        (score_df['Volume_Rank'] * CONFIG['Weights']['Volume']) +
        (score_df['Structure_Rank'] * CONFIG['Weights']['Structure'])
    )
    
    # --- PENALTY BOX (HARD FILTERS) ---
    # Set score to 0 for disqualified stocks
    penalty_mask = (
        score_df['Broken_Trend'] |
        score_df['ATR_Spike'] |
        (score_df['Avg_Turnover_Cr'] < CONFIG['Min_Turnover_Cr']) |
        (score_df['Close'] < CONFIG['Min_Price']) |
        (~score_df['Golden_Cross'].astype(bool))
    )
    
    score_df.loc[penalty_mask, 'Final_Score'] = 0
    
    return score_df.sort_values(by='Final_Score', ascending=False)

