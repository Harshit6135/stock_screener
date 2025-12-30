import pandas as pd
from datetime import datetime, date
from config import *
from config import Strategy1Parameters as StrategyParams
from repositories import IndicatorsRepository, MarketDataRepository, RankingRepository
from utils import (score_rsi_regime, score_percent_b, score_trend_extension,
                   z_score_normalize, percentile_rank)

ranking_repo = RankingRepository()
indicators_repo = IndicatorsRepository()
marketdata_repo = MarketDataRepository()
logger = setup_logger(name="Orchestrator")


class RankingService:
    """
    Multi-Factor Momentum Scorecard for Indian Markets
    Based on quantitative equity ranking framework
    """
    def __init__(self):
        self.strategy_params = StrategyParams()

    @staticmethod
    def _calculate_percentile_ranks(metrics_df) -> pd.DataFrame:
        """Calculate percentile ranks across the universe"""

        # Define metrics to rank
        rank_cols = {
            'ema_50_slope': 'trend_rank',
            'ppo_12_26_9': 'momentum_ppo_rank',
            'ppoh_12_26_9': 'momentum_ppoh_rank',
            'risk_adjusted_return': 'efficiency_rank',
            'rvol': 'rvolume_rank',
            'price_vol_correlation': 'price_vol_corr_rank',
            'bbb_20_2_2': 'structure_rank'
        }
        
        for col, rank_name in rank_cols.items():
            if col in metrics_df.columns:
                # Use Z-score for BB Width, percentile for others (per report appendix)
                # if col == 'bbb_20_2_2':
                #     metrics_df[rank_name] = z_score_normalize(metrics_df[col])
                # else:
                #     metrics_df[rank_name] = percentile_rank(metrics_df[col])
                metrics_df[rank_name] = percentile_rank(metrics_df[col])
        
        metrics_df['momentum_rsi_rank'] = score_rsi_regime(metrics_df['rsi_signal_ema_3'])
        metrics_df['trend_extension_rank'] = score_trend_extension(metrics_df['distance_from_ema_200'])
        metrics_df['trend_start_rank'] = score_trend_extension(metrics_df['distance_from_ema_50'])
        metrics_df['structure_bb_rank'] = score_percent_b(metrics_df['percent_b'])

        return metrics_df

    def _calculate_weighted_composite(self, metrics_df) -> pd.DataFrame:
        """Calculate weighted composite score"""
        
        # Aggregate trend (combine EMA slope and extension)
        if 'trend_rank' in metrics_df.columns and 'trend_extension_rank' in metrics_df.columns:
            metrics_df['final_trend_score'] = (
                metrics_df['trend_rank'].fillna(0) * self.strategy_params.trend_rank_weight +
                metrics_df['trend_extension_rank'].fillna(0) * self.strategy_params.trend_extension_rank_weight
            )
        else:
            metrics_df['final_trend_score'] = metrics_df.get('trend_rank', 0)

        # Aggregate momentum (RSI + PPO)
        momentum_cols = [c for c in ['momentum_rsi_rank', 'momentum_ppo_rank', 'momentum_ppoh_rank'] 
                        if c in metrics_df.columns]
        if momentum_cols:
            metrics_df['final_momentum_score'] = (metrics_df["momentum_rsi_rank"] * self.strategy_params.momentum_rsi_rank_weight + 
                                              metrics_df["momentum_ppo_rank"] * self.strategy_params.momentum_ppo_rank_weight + 
                                              metrics_df["momentum_ppoh_rank"] * self.strategy_params.momentum_ppoh_rank_weight)
        else:
            metrics_df['final_momentum_score'] = 0
        
        metrics_df['final_vol_score'] = (metrics_df["rvolume_rank"] * self.strategy_params.rvolume_rank_weight + 
                               metrics_df["price_vol_corr_rank"] * self.strategy_params.price_vol_corr_rank_weight)

        # Combine BB Width and %B for structure (as per report Section 4.1)
        metrics_df['final_structure_score'] = (
            metrics_df.get('structure_rank', 0) * self.strategy_params.structure_rank_weight +
            metrics_df.get('structure_bb_rank', 0) * self.strategy_params.structure_bb_rank_weight
        )

        # Calculate composite score
        metrics_df['composite_score'] = (
            self.strategy_params.trend_strength_weight * metrics_df.get('final_trend_score', 0) +
            self.strategy_params.momentum_velocity_weight * metrics_df.get('final_momentum_score', 0) +
            self.strategy_params.risk_efficiency_weight * metrics_df.get('efficiency_rank', 0) +
            self.strategy_params.conviction_weight * metrics_df.get('final_vol_score', 0) +
            self.strategy_params.structure_weight * metrics_df.get('final_structure_score', 0)
        )
        metrics_df[metrics_df['tradingsymbol']=='DCXINDIA'].to_csv("Test.csv")
        return metrics_df

    def _apply_universe_penalties(self, metrics_df) -> pd.DataFrame:
        """Apply penalty box rules across universe"""
        metrics_df.loc[metrics_df['ema_200'] > metrics_df['close'], 'composite_score'] = 0
        metrics_df.loc[metrics_df['atrr_14'] / metrics_df['atrr_14'].shift(2) > self.strategy_params.atr_threshold, 'composite_score'] = 0
        #metrics_df.loc[metrics_df['volume']*metrics_df['close'] < self.strategy_params.turnover_threshold * 10000000, 'composite_score'] = 0
        metrics_df.loc[metrics_df['ema_50'] > metrics_df['close'], 'composite_score'] = 0
        metrics_df['composite_score'] = metrics_df['composite_score'].fillna(0)
        return metrics_df

    # ============= COMPOSITE SCORECARD =============
    def calculate_composite_score(self, metrics_df) -> pd.DataFrame:
        """
        Calculate composite score for multiple stocks
        Args:
            metrics_df: DataFrame with OHLCV data
        Returns:
            DataFrame with stocks and their factor scores + composite score
        """
        metrics_df = self._calculate_percentile_ranks(metrics_df)

        # Calculate composite scores
        # metrics_df = self._calculate_weighted_composite(metrics_df)

        # # Apply penalty box
        # metrics_df = self._apply_universe_penalties(metrics_df)

        # # Sort by composite score
        # metrics_df = metrics_df.sort_values('composite_score', ascending=False)
        req_cols = [
            'tradingsymbol',
            'ema_50_slope',
            'trend_rank',
            'distance_from_ema_200',
            'trend_extension_rank',
            'distance_from_ema_50',
            'trend_start_rank',
            # 'final_trend_score',
            'rsi_signal_ema_3',
            'momentum_rsi_rank',
            'ppo_12_26_9',
            'momentum_ppo_rank',
            'ppoh_12_26_9',
            'momentum_ppoh_rank',
            # 'final_momentum_score',
            'risk_adjusted_return',
            'efficiency_rank',
            'rvol',
            'rvolume_rank',
            'price_vol_correlation',
            'price_vol_corr_rank',
            # 'final_vol_score',
            'bbb_20_2_2',
            'structure_rank',
            'percent_b',
            'structure_bb_rank',
            # 'final_structure_score',
            # 'composite_score'
        ]
        return metrics_df[req_cols]

    @staticmethod
    def query_to_dict(results):
        return [
            {c.name: getattr(row, c.name) for c in row.__table__.columns}
            for row in results
        ]

    def generate_score(self, date=None):
        """
        Orchestrates the ranking process:
        1. Fetch instruments
        2. Fetch latest price and indicator data for each instrument
        3. Construct DataFrames
        4. Calculate composite scores
        5. Save to ranking table with date
        """
        logger.info("Starting Ranking Calculation...")
        if not date:
            max_date = marketdata_repo.get_max_date_from_table()
            date_range = {
                "start_date": max_date,
                "end_date": max_date
            }
        else:
            date_range = {
                "start_date": date,
                "end_date": date
            }

        #print(date_range)

        price_data_list = self.query_to_dict(marketdata_repo.get_prices_for_all_stocks(date_range))
        indicators_data_list = self.query_to_dict(indicators_repo.get_indicators_for_all_stocks(date_range))

        # 3. Create DataFrames
        stocks_df = pd.DataFrame(price_data_list)
        metrics_df = pd.DataFrame(indicators_data_list)

        if len(stocks_df) == 0 or len(metrics_df) == 0:
            logger.info("No data found for date: {}".format(date))
            return None

        metrics_df = pd.merge(metrics_df, stocks_df, on='tradingsymbol', how='inner')
        #metrics_df = metrics_df[metrics_df['close'] >= metrics_df['ema_50']]
        ranked_df = self.calculate_composite_score(metrics_df)
        
        # Add ranking date and position
        ranking_date = date
        ranked_df['ranking_date'] = ranking_date
        # ranked_df = ranked_df.sort_values('composite_score', ascending=False)
        # ranked_df['rank'] = range(1, len(ranked_df) + 1)
        # 5. Save to database
        logger.info("Saving rankings to database...")
        response = ranking_repo.delete(ranking_date)
        if response:
            ranking_repo.bulk_insert(ranked_df.to_dict('records'))
        else:
            logger.error("Failed to delete existing rankings for today, cannot save new rankings")
            return None
        logger.info(f"Saved {len(ranked_df)} rankings to database for {ranking_date}")
        # ranked_df.to_csv(f"data/ranked {date}.csv", index=False)
        return True

    # def calculate_score(self):
    #     logger.info("Starting to update score (API Mode)...")

    #     logger.info("Fetching Instruments from DB...")
    #     instruments = instr_repo.get_all_instruments()

    #     logger.info("Calculating score for Instruments...")
    #     yesterday = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)
        
    #     for i, instr in enumerate(instruments):
    #         print(instr)
    #         tradingsymbol = instr.tradingsymbol
    #         instr_token = instr.instrument_token
    #         exchange = instr.exchange
    #         log_symb = f"{tradingsymbol} ({instr_token})"
    #         logger.info(f"Processing {i+1}/{len(instruments)} {log_symb})...")

    #         last_data_date = marketdata_repo.get_latest_date_by_symbol(tradingsymbol)
    #         if last_data_date:
    #             last_data_date = pd.to_datetime(last_data_date.date)
    #         else:
    #             logger.error(f"No market data found for {log_symb}")
    #             continue

    #         last_ind_date = indicators_repo.get_latest_date_by_symbol(tradingsymbol)
    #         if last_ind_date:
    #             last_ind_date = pd.to_datetime(last_ind_date.date)
    #             if last_ind_date == last_data_date:
    #                 logger.info(f"Indicators up to date for {log_symb}.")
    #                 continue
    #             calc_start_date = last_ind_date - timedelta(days=additional_parameters['ema_200_lookback'])
    #         else:
    #             calc_start_date = pd.to_datetime("2000-01-01")
    #             last_ind_date = calc_start_date

    #         query_payload = {
    #             "tradingsymbol": tradingsymbol,
    #             "start_date": str(calc_start_date.date()),
    #             "end_date": str(yesterday.date())
    #         }
    #         md_output = marketdata_repo.query(query_payload)
    #         md_list = [{column.name:getattr(row, column.name) for column in row.__table__.columns} for row in md_output]

    #         if len(md_list)<200:
    #             logger.error(f"Less than 200 days data")
    #             continue        

    #         df_for_ind = pd.DataFrame(md_list)
    #         df_for_ind['date'] = pd.to_datetime(df_for_ind['date'])
    #         df_for_ind.set_index('date', inplace=True)
    #         df_for_ind.sort_index(inplace=True)
            
    #         logger.info("Calculating indicators...")

    #         ind_df = self.apply_study(df_for_ind, last_ind_date)
    #         ind_df = self._calculate_derived_indicators(ind_df)
    #         ind_df.columns = ind_df.columns.str.lower().str.replace(".0", "")
    #         ind_df = ind_df.drop(columns=['open', 'high', 'low', 'close', 'volume'], errors='ignore')
    #         ind_df.reset_index(inplace=True)
    #         ind_df['instrument_token'] = instr_token
    #         ind_df['tradingsymbol'] = tradingsymbol
    #         ind_df['exchange'] = exchange

    #         if last_ind_date:
    #             next_day = last_ind_date + timedelta(days=1)
    #             ind_df_filtered = ind_df[ind_df['date'] >= next_day]
    #         else:
    #             ind_df_filtered = ind_df
    #         if ind_df_filtered.empty:
    #             logger.info(f"No new data to calculate indicators for {log_symb}")
    #             continue
            
    #         ind_df_filtered['date'] = ind_df_filtered['date'].dt.date   
    #         ind_json = ind_df_filtered.to_dict(orient='records')
    #         indicators_repo.bulk_insert(ind_json)

    #     logger.info("Indicators updated successfully.")
    def backfill_rankings(self):
        """
        Generates scores for all dates since the last updated date in the ranking table.
        If no rankings exist, starts from the earliest available market data date.
        """
        last_ranking_date = ranking_repo.get_max_ranking_date()
        
        if last_ranking_date:
            start_date = last_ranking_date
        else:
            start_date = marketdata_repo.get_min_date_from_table()
        
        current_date = pd.Timestamp.now().normalize()
        if isinstance(start_date, (datetime, date)):
            start_date = pd.Timestamp(start_date)

        while start_date <= current_date:            
            print(start_date)
            self.generate_score(start_date)
            start_date += pd.Timedelta(days=1)
