import pandas as pd
from typing import Optional
from utils.normalize_mthds import percentile_rank, z_score_normalize
from utils.scoring_methods import score_rsi_regime, score_trend_extension, score_percent_b
from utils.penalty_box import apply_penalty_box


class IndicatorWeights:
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
    
    def __init__(self, stock_df, metrics_df, weights: Optional[IndicatorWeights] = None):
        self.stock_df = stock_df
        self.metrics_df = metrics_df
        self.weights = weights or IndicatorWeights()

    # Apply Goldilocks penalty for overextension (Z > 2.5)
    @staticmethod
    def goldilocks_penalty(z_score, dist):
        if pd.isna(dist) or dist < 0:
            return 0
        # Penalize Z-scores > 2.5 (overextended per PDF Section 3.2.2)
        if z_score > 75:  # Equivalent to Z > 2.5
            return z_score * 0.6  # 40% penalty
        return z_score

    # Non-linear scoring for distance (Goldilocks zone)
    @staticmethod
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
            return 40  

    def _calculate_percentile_ranks(self) -> pd.DataFrame:
        """Calculate percentile ranks across the universe"""
        
        ranked = self.metrics_df.copy()
        
        # Define metrics to rank
        rank_cols = {
            'ema_50_slope': 'trend_rank',
            'ppo_12_26_9': 'momentum_ppo_rank',
            'ppoh_12_26_9': 'momentum_ppoh_rank',
            'risk_adj_return': 'efficiency_rank',
            'rvol': 'rvolume_rank',
            'price_vol_correlation': 'price_vol_corr_rank',
            'bbb_20_2_2': 'structure_rank'
        }
        
        for col, rank_name in rank_cols.items():
            if col in ranked.columns:
                ranked[rank_name] = percentile_rank(ranked[col])
        
        # Use pre-scored metrics
        ranked['momentum_rsi_rank'] = score_rsi_regime(ranked['rsi_14'])

        # dist = ranked['distance_from_ema_200']
        # dist_z = z_score_normalize(dist)
        #
        # ranked['trend_extension_rank'] = [
        #     self.goldilocks_penalty(z, d) if not pd.isna(d) else 0
        #     for z, d in zip(dist_z, dist)
        # ]

        # ranked['trend_extension_rank'] = score_trend_extension(ranked['distance_from_ema_200'])
        # ranked['trend_extension_rank'] = z_score_normalize(ranked['distance_from_ema_200'])
        dist_score = ranked['distance_from_ema_200'].apply(self.goldilocks_dist)
        dist_score = ranked.apply(lambda row: self.goldilocks_penalty(
            z_score_normalize(pd.Series([row['distance_from_ema_200']])).iloc[0]
            if not pd.isna(row['distance_from_ema_200']) else 0,
            row['distance_from_ema_200']
        ), axis=1)
        ranked['trend_extension_rank'] = dist_score
        # if 'percent_b_score' in ranked.columns:
        ranked['structure_bb_rank'] = score_percent_b(ranked['percent_b'])
        
        return ranked

    def _calculate_weighted_composite(self, ranked_df) -> pd.DataFrame:
        """Calculate weighted composite score"""
        
        result =  ranked_df.copy()
        # Aggregate trend (combine EMA slope and extension)
        if 'trend_rank' in result.columns and 'trend_extension_rank' in result.columns:
            result['final_trend_score'] = (
                result['trend_rank'].fillna(0) * 0.6 +
                result['trend_extension_rank'].fillna(0) * 0.4
            )
        else:
            result['final_trend_score'] = result.get('trend_rank', 0)

        # Aggregate momentum (RSI + PPO)
        momentum_cols = [c for c in ['momentum_rsi_rank', 'momentum_ppo_rank', 'momentum_ppoh_rank'] 
                        if c in result.columns]
        if momentum_cols:
            result['final_momentum_score'] = (result["momentum_rsi_rank"] * 0.5 + 
                                                result["momentum_ppo_rank"] * 0.3 + 
                                                result["momentum_ppoh_rank"] * 0.2)
        else:
            result['final_momentum_score'] = 0
        
        result['vol_score'] = (result["rvolume_rank"] * 0.7 + 
                                                result["price_vol_corr_rank"] * 0.3)

        # Calculate composite score
        result['composite_score'] = (
            self.weights.trend_strength * result.get('final_trend_score', 0) +
            self.weights.momentum_velocity * result.get('final_momentum_score', 0) +
            self.weights.risk_efficiency * result.get('efficiency_rank', 0) +
            self.weights.conviction * result.get('vol_score', 0) +
            self.weights.structure * result.get('structure_rank', 0)
        )
        
        return result

    def _apply_universe_penalties(self, ranked_df) -> pd.DataFrame:
        """Apply penalty box rules across universe"""
        
        result = ranked_df.copy()
        
        for idx, row in result.iterrows():
            symbol = row['symbol']
            if symbol in self.stock_df:
                df = self.stock_df[symbol]
                penalized_score = self.apply_penalty_box(
                    df, 
                    pd.Series([row['composite_score']])
                )
                result.at[idx, 'composite_score'] = penalized_score.iloc[0]
        
        return result
    
    # ============= COMPOSITE SCORECARD =============
    def calculate_composite_score(self) -> pd.DataFrame:
        """
        Calculate composite score for multiple stocks
        Args:
            metrics_df: DataFrame with OHLCV data
        Returns:
            DataFrame with stocks and their factor scores + composite score
        """
        # Calculate percentile ranks across universe
        ranked_df = self._calculate_percentile_ranks()

        # Calculate composite scores
        ranked_df = self._calculate_weighted_composite(ranked_df)

        # Apply penalty box
        ranked_df = self._apply_universe_penalties(ranked_df)

        # Sort by composite score
        ranked_df = ranked_df.sort_values('composite_score', ascending=False)

        return ranked_df