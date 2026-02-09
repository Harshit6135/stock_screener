# Codebase Review Checklist

Use this checklist to track your review progress. 'Calls' lists functions called within the definition to help trace logic.

### db.py (No definitions)

### local_secrets.example.py (No definitions)

### local_secrets.py (No definitions)

### run.py

- [ ] **def create_app(config_class)**
    - *Calls*: `Flask`, `app.config.from_object`
- [ ] **def dashboard()**
    - *Calls*: `app.route`, `render_template`
- [ ] **def backtest()**
    - *Calls*: `app.route`, `render_template`
- [ ] **def actions()**
    - *Calls*: `app.route`, `render_template`

## config

### __init__.py (No definitions)

### app_config.py (No definitions)

### flask_config.py

- [ ] **class Config**

### indicators_config.py (No definitions)

### kite_config.py (No definitions)

### logger_config.py

- [ ] **def setup_logger(name, log_dir)**
    - *Calls*: `console_handler.setFormatter`, `console_handler.setLevel`, `datetime.now`, `file_handler.setFormatter`, `file_handler.setLevel`, `jsonlogger.JsonFormatter`, `logger.addHandler`, `logger.handlers.clear`, `logger.hasHandlers`, `logger.setLevel`, `logging.FileHandler`, `logging.Formatter`, `logging.StreamHandler`, `logging.getLogger`, `os.makedirs`, `os.path.join`, `strftime`

### strategies_config.py

- [ ] **class Strategy1Parameters**
- [ ] **class TransactionCostConfig**
- [ ] **class ImpactCostConfig**
- [ ] **class PenaltyBoxConfig**
- [ ] **class PositionSizingConfig**
- [ ] **class PortfolioControlConfig**
- [ ] **class TaxConfig**
- [ ] **class ChallengerConfig**
- [ ] **class GoldilocksConfig**
- [ ] **class RSIRegimeConfig**
- [ ] **class BacktestConfig**

## scripts

### generate_reference_checklist.py

- [ ] **class ReferenceVisitor**
- [ ] **def ReferenceVisitor.__init__(self)**
- [ ] **def ReferenceVisitor.visit_FunctionDef(self, node)**
    - *Calls*: `self._handle_func`
- [ ] **def ReferenceVisitor.visit_AsyncFunctionDef(self, node)**
    - *Calls*: `self._handle_func`
- [ ] **def ReferenceVisitor.visit_ClassDef(self, node)**
    - *Calls*: `self.definitions.append`, `self.generic_visit`
- [ ] **def ReferenceVisitor._handle_func(self, node)**
    - *Calls*: `self.definitions.append`, `self.generic_visit`, `set`
- [ ] **def ReferenceVisitor.visit_Call(self, node)**
    - *Calls*: `self._get_func_name`, `self.calls.add`, `self.generic_visit`
- [ ] **def ReferenceVisitor._get_func_name(self, node)**
    - *Calls*: `isinstance`, `self._get_func_name`
- [ ] **def generate_checklist(root_dir)**
    - *Calls*: `Path`, `ReferenceVisitor`, `ast.parse`, `dirnames.sort`, `f.endswith`, `f.read`, `filenames.sort`, `join`, `open`, `os.path.join`, `os.path.relpath`, `os.walk`, `print`, `resolve`, `sorted`, `visitor.visit`

## src

### __init__.py (No definitions)

## src\adaptors

### yfinance_adaptor.py

- [ ] **class YFinanceAdaptor**
    - Docstrings missing
- [ ] **def YFinanceAdaptor.get_stock_info(tickers_list)**
    - Docstrings missing
    - *Calls*: `logger.error`, `yf.Ticker`

## src\api\v1\routes

### __init__.py (No definitions)

### actions_routes.py

- [ ] **class GenerateActions**
- [ ] **def GenerateActions.post(self)**
    - *Calls*: `ActionsService`, `abort`, `actions.generate_actions`, `blp.doc`, `blp.response`, `date`, `datetime.now`, `logger.error`, `str`
- [ ] **class ActionDates**
- [ ] **def ActionDates.get(self)**
    - *Calls*: `InvestmentRepository.get_action_dates`, `blp.doc`, `blp.response`
- [ ] **class ActionsList**
- [ ] **def ActionsList.get(self, args)**
    - *Calls*: `ActionSchema`, `InvestmentRepository.get_actions`, `a.to_dict`, `args.get`, `blp.arguments`, `blp.doc`, `blp.response`
- [ ] **class ActionDetail**
- [ ] **def ActionDetail.put(self, data, action_id)**
    - *Calls*: `InvestmentRepository.update_action`, `abort`, `blp.arguments`, `blp.doc`, `blp.response`

### app_routes.py

- [ ] **class CleanupAfterDate**
- [ ] **def CleanupAfterDate.delete(self, args)**
    - *Calls*: `IndicatorsRepository`, `MarketDataRepository`, `PercentileRepository`, `ScoreRepository`, `blp.arguments`, `blp.doc`, `blp.response`, `indicators_repo.delete_after_date`, `marketdata_repo.delete_after_date`, `percentile_repo.delete_after_date`, `score_repo.delete_after_date`, `score_repo.delete_ranking_after_date`
- [ ] **class RunPipeline**
- [ ] **def RunPipeline.post(self)**
    - *Calls*: `IndicatorsService`, `InitService`, `MarketDataService`, `PercentileService`, `RankingService`, `ScoreService`, `blp.doc`, `blp.response`, `indicators_service.calculate_indicators`, `init_service.initialize_app`, `marketdata_service.update_latest_data_for_all`, `percentile_service.backfill_percentiles`, `ranking_service.generate_rankings`, `score_service.generate_composite_scores`, `str`

### backtest_routes.py

- [ ] **class RunBacktest**
- [ ] **def RunBacktest.post(self, data)**
    - *Calls*: `abort`, `blp.arguments`, `blp.doc`, `blp.response`, `date`, `datetime.strptime`, `logger.error`, `run_backtest`, `str`, `summary.get`

### config_routes.py

- [ ] **class StrategyConfigResource**
- [ ] **def StrategyConfigResource.get(self, strategy_name)**
    - *Calls*: `ConfigRepository`, `blp.doc`, `blp.response`, `config_repo.get_config`
- [ ] **def StrategyConfigResource.put(self, data, strategy_name)**
    - *Calls*: `ConfigRepository`, `blp.arguments`, `blp.doc`, `blp.response`, `config_repo.get_config`, `config_repo.update_config`

### costs_routes.py

- [ ] **class RoundTripCosts**
- [ ] **def RoundTripCosts.get(self)**
    - *Calls*: `abort`, `blp.doc`, `calculate_round_trip_cost`, `float`, `request.args.get`
- [ ] **class BuyCosts**
- [ ] **def BuyCosts.get(self)**
    - *Calls*: `abort`, `blp.doc`, `calculate_buy_costs`, `float`, `request.args.get`
- [ ] **class SellCosts**
- [ ] **def SellCosts.get(self)**
    - *Calls*: `abort`, `blp.doc`, `calculate_sell_costs`, `float`, `request.args.get`
- [ ] **class PositionSize**
- [ ] **def PositionSize.get(self)**
    - *Calls*: `abort`, `all`, `blp.doc`, `calculate_position_size`, `float`, `request.args.get`
- [ ] **class EqualWeightSize**
- [ ] **def EqualWeightSize.get(self)**
    - *Calls*: `abort`, `all`, `blp.doc`, `calculate_equal_weight_position`, `float`, `int`, `request.args.get`, `str`

### indicators_routes.py

- [ ] **class Indicators**
- [ ] **def Indicators.post(self, indicator_data)**
    - *Calls*: `IndicatorsSchema`, `abort`, `blp.arguments`, `blp.doc`, `blp.response`, `indicators_repository.bulk_insert`
- [ ] **class IndicatorsQuery**
- [ ] **def IndicatorsQuery.get(self, filter_data)**
    - *Calls*: `IndicatorsSchema`, `blp.arguments`, `blp.doc`, `blp.response`, `indicators_repository.query`
- [ ] **class LatestIndicatorsData**
- [ ] **def LatestIndicatorsData.get(self, tradingsymbol)**
    - *Calls*: `blp.doc`, `blp.response`, `indicators_repository.get_latest_date_by_symbol`
- [ ] **class IndicatorsMaxDate**
- [ ] **def IndicatorsMaxDate.get(self)**
    - *Calls*: `MaxDateSchema`, `blp.doc`, `blp.response`, `indicators_repository.get_latest_date_for_all`
- [ ] **class IndicatorsQueryAll**
- [ ] **def IndicatorsQueryAll.get(self, filter_data)**
    - *Calls*: `IndicatorsSchema`, `append`, `blp.arguments`, `blp.response`, `indicators_repository.get_indicators_for_all_stocks`
- [ ] **class IndicatorsDelete**
- [ ] **def IndicatorsDelete.delete(self, tradingsymbol)**
    - *Calls*: `IndicatorsSchema`, `abort`, `blp.arguments`, `blp.response`, `indicators_repository.delete_by_tradingsymbol`
- [ ] **class IndicatorsUpdateAll**
- [ ] **def IndicatorsUpdateAll.post(self)**
    - *Calls*: `IndicatorsService`, `blp.doc`, `indicators_service.calculate_indicators`
- [ ] **class IndicatorByName**
- [ ] **def IndicatorByName.get(self, indicator_name)**
    - *Calls*: `abort`, `blp.doc`, `date`, `datetime.strptime`, `indicators_repository.get_indicator_by_tradingsymbol`, `request.args.get`

### init_routes.py

- [ ] **class Init**
- [ ] **def Init.post(self)**
    - *Calls*: `InitService`, `abort`, `blp.doc`, `blp.response`, `init_service.initialize_app`, `str`

### instrument_routes.py

- [ ] **class InstrumentList**
- [ ] **def InstrumentList.get(self)**
    - *Calls*: `InstrumentSchema`, `blp.doc`, `blp.response`, `instr_repository.get_all_instruments`
- [ ] **def InstrumentList.post(self, instrument_data)**
    - *Calls*: `InstrumentSchema`, `abort`, `blp.arguments`, `blp.doc`, `blp.response`, `instr_repository.bulk_insert`
- [ ] **def InstrumentList.delete(self)**
    - *Calls*: `abort`, `blp.doc`, `blp.response`, `instr_repository.delete_all`
- [ ] **class Instrument**
- [ ] **def Instrument.get(self, instrument_token)**
    - *Calls*: `abort`, `blp.doc`, `blp.response`, `instr_repository.get_by_token`
- [ ] **def Instrument.put(self, instrument_data, instrument_token)**
    - *Calls*: `abort`, `blp.arguments`, `blp.doc`, `blp.response`, `instr_repository.update_instrument`

### investment_routes.py

- [ ] **class HoldingDates**
- [ ] **def HoldingDates.get(self)**
    - *Calls*: `InvestmentRepository.get_holdings_dates`, `blp.doc`, `blp.response`
- [ ] **class Holdings**
- [ ] **def Holdings.get(self, args)**
    - *Calls*: `HoldingSchema`, `InvestmentRepository.get_holdings`, `args.get`, `blp.arguments`, `blp.doc`, `blp.response`, `h.to_dict`
- [ ] **class Summary**
- [ ] **def Summary.get(self, args)**
    - *Calls*: `InvestmentRepository.get_summary`, `args.get`, `blp.arguments`, `blp.doc`, `blp.response`, `summary.to_dict`

### marketdata_routes.py

- [ ] **class MarketData**
- [ ] **def MarketData.post(self, market_data)**
    - *Calls*: `MarketDataSchema`, `abort`, `blp.arguments`, `blp.doc`, `blp.response`, `marketdata_repo.bulk_insert`
- [ ] **class MarketDataQuery**
- [ ] **def MarketDataQuery.get(self, filter_data)**
    - *Calls*: `MarketDataSchema`, `blp.arguments`, `blp.doc`, `blp.response`, `marketdata_repo.query`
- [ ] **class MarketsDataMaxDate**
- [ ] **def MarketsDataMaxDate.get(self)**
    - *Calls*: `MaxDateSchema`, `blp.doc`, `blp.response`, `marketdata_repo.get_latest_date_for_all`
- [ ] **class LatestMarketData**
- [ ] **def LatestMarketData.get(self, tradingsymbol)**
    - *Calls*: `blp.doc`, `blp.response`, `marketdata_repo.get_latest_date_by_symbol`
- [ ] **class MarketDataQueryAll**
- [ ] **def MarketDataQueryAll.get(self, filter_data)**
    - *Calls*: `MarketDataSchema`, `append`, `blp.arguments`, `blp.response`, `marketdata_repo.get_prices_for_all_stocks`
- [ ] **class MarketDataDelete**
- [ ] **def MarketDataDelete.delete(self, tradingsymbol)**
    - *Calls*: `MarketDataSchema`, `abort`, `blp.arguments`, `blp.response`, `marketdata_repo.delete_by_tradingsymbol`
- [ ] **class MarketDataUpdateAll**
- [ ] **def MarketDataUpdateAll.post(self)**
    - *Calls*: `MarketDataService`, `blp.doc`, `marketdata_service.update_latest_data_for_all`
- [ ] **class MarketDataUpdateAllHistorical**
- [ ] **def MarketDataUpdateAllHistorical.post(self)**
    - *Calls*: `MarketDataService`, `blp.doc`, `marketdata_service.update_latest_data_for_all`
- [ ] **class MarketDataBySymbol**
- [ ] **def MarketDataBySymbol.get(self, tradingsymbol)**
    - *Calls*: `abort`, `blp.doc`, `blp.response`, `date`, `datetime.strptime`, `marketdata_repo.get_latest_date_by_symbol`, `marketdata_repo.get_marketdata_by_trading_symbol`, `request.args.get`

### percentile_routes.py

- [ ] **class PercentileList**
- [ ] **def PercentileList.post(self, percentile_data)**
    - *Calls*: `PercentileSchema`, `abort`, `blp.arguments`, `blp.doc`, `blp.response`, `len`, `percentile_repository.bulk_insert`
- [ ] **class PercentileUpdateAll**
- [ ] **def PercentileUpdateAll.post(self, percentile_data)**
    - *Calls*: `PercentileAllSchema`, `PercentileService`, `blp.arguments`, `blp.doc`, `blp.response`, `percentile_data.get`, `percentile_service.generate_percentile`
- [ ] **class PercentileUpdateByDate**
- [ ] **def PercentileUpdateByDate.post(self, percentile_date)**
    - *Calls*: `PercentileService`, `blp.doc`, `blp.response`, `percentile_service.generate_percentile`
- [ ] **class UpdateAllPercentiles**
- [ ] **def UpdateAllPercentiles.post(self)**
    - *Calls*: `PercentileService`, `blp.doc`, `blp.response`, `percentile_service.backfill_percentiles`
- [ ] **class PercentilesQuery**
- [ ] **def PercentilesQuery.get(self, percentile_date)**
    - *Calls*: `PercentileSchema`, `blp.doc`, `blp.response`, `percentile_repository.get_percentiles_by_date`

### ranking_routes.py

- [ ] **def get_prev_friday(d)**
    - *Calls*: `d.weekday`, `timedelta`
- [ ] **class GenerateRankings**
- [ ] **def GenerateRankings.post(self)**
    - *Calls*: `RankingService`, `blp.doc`, `blp.response`, `ranking_service.generate_rankings`
- [ ] **class RecalculateRankings**
- [ ] **def RecalculateRankings.post(self)**
    - *Calls*: `RankingService`, `blp.doc`, `blp.response`, `ranking_service.recalculate_all_rankings`
- [ ] **class TopRankings**
- [ ] **def TopRankings.get(self, n)**
    - *Calls*: `TopNSchema`, `abort`, `blp.doc`, `blp.response`, `date`, `datetime.strptime`, `get_prev_friday`, `request.args.get`, `score_repo.get_top_n_by_date`
- [ ] **class RankingBySymbol**
- [ ] **def RankingBySymbol.get(self, symbol)**
    - *Calls*: `abort`, `blp.doc`, `blp.response`, `date`, `datetime.strptime`, `get_prev_friday`, `marketdata_repo.get_latest_date_by_symbol`, `marketdata_repo.query`, `request.args.get`, `score_repo.get_by_symbol`
- [ ] **class RankingsQuery**
- [ ] **def RankingsQuery.get(self, ranking_date_str)**
    - *Calls*: `RankingSchema`, `blp.doc`, `blp.response`, `score_repo.get_rankings_by_date`

### score_routes.py

- [ ] **class GenerateScores**
- [ ] **def GenerateScores.post(self)**
    - *Calls*: `ScoreService`, `blp.doc`, `blp.response`, `score_service.generate_composite_scores`
- [ ] **class RecalculateScores**
- [ ] **def RecalculateScores.post(self)**
    - *Calls*: `ScoreService`, `blp.doc`, `blp.response`, `score_service.recalculate_all_scores`
- [ ] **class ScoreBySymbol**
- [ ] **def ScoreBySymbol.get(self, tradingsymbol)**
    - *Calls*: `abort`, `blp.doc`, `date`, `datetime.strptime`, `request.args.get`, `score_repo.get_by_symbol`

### tax_routes.py

- [ ] **class TaxEstimate**
- [ ] **def TaxEstimate.get(self)**
    - *Calls*: `abort`, `all`, `blp.doc`, `calculate_capital_gains_tax`, `date`, `datetime.strptime`, `float`, `int`, `request.args.get`
- [ ] **class HoldForLTCG**
- [ ] **def HoldForLTCG.get(self)**
    - *Calls*: `abort`, `all`, `blp.doc`, `date`, `datetime.strptime`, `float`, `request.args.get`, `should_hold_for_ltcg`
- [ ] **class TaxAdjustedCost**
- [ ] **def TaxAdjustedCost.get(self)**
    - *Calls*: `abort`, `all`, `blp.doc`, `calculate_tax_adjusted_cost`, `date`, `datetime.strptime`, `float`, `int`, `request.args.get`

## src\backtesting

### __init__.py (No definitions)

### api_client.py

- [ ] **class BacktestAPIClient**
- [ ] **def BacktestAPIClient.__init__(self, base_url)**
    - *Calls*: `os.getenv`, `requests.Session`
- [ ] **def BacktestAPIClient.get_top_rankings(self, n, as_of_date)**
    - *Calls*: `as_of_date.isoformat`, `logger.error`, `response.json`, `response.raise_for_status`, `self.session.get`
- [ ] **def BacktestAPIClient.get_indicator(self, indicator_name, tradingsymbol, as_of_date)**
    - *Calls*: `as_of_date.isoformat`, `data.get`, `logger.warning`, `response.json`, `self.session.get`
- [ ] **def BacktestAPIClient.get_market_data(self, tradingsymbol, as_of_date)**
    - *Calls*: `as_of_date.isoformat`, `logger.warning`, `response.json`, `self.session.get`
- [ ] **def BacktestAPIClient.get_close_price(self, tradingsymbol, as_of_date)**
    - *Calls*: `data.get`, `self.get_market_data`
- [ ] **def BacktestAPIClient.get_low_price(self, tradingsymbol, as_of_date)**
    - *Calls*: `data.get`, `self.get_market_data`
- [ ] **def BacktestAPIClient.get_score(self, tradingsymbol, as_of_date)**
    - *Calls*: `as_of_date.isoformat`, `data.get`, `logger.warning`, `response.json`, `self.session.get`
- [ ] **def BacktestAPIClient.calculate_transaction_costs(self, trade_value, order_pct_adv)**
    - *Calls*: `response.json`, `self.session.get`
- [ ] **def BacktestAPIClient.estimate_tax(self, purchase_price, current_price, purchase_date, current_date, quantity)**
    - *Calls*: `current_date.isoformat`, `purchase_date.isoformat`, `response.json`, `self.session.get`

### config.py

- [ ] **class FetchedConfig**
- [ ] **class BacktestConfigLoader**
- [ ] **def BacktestConfigLoader.__init__(self, base_url)**
    - *Calls*: `os.getenv`
- [ ] **def BacktestConfigLoader.fetch(self, strategy_name)**
    - *Calls*: `BaseBacktestConfig`, `ChallengerConfig`, `FetchedConfig`, `PositionSizingConfig`, `data.get`, `logger.warning`, `requests.get`, `response.json`
- [ ] **def BacktestConfigLoader.config(self)**
    - *Calls*: `self.fetch`

### models.py

- [ ] **class Position**
- [ ] **def Position.investment_value(self)**
- [ ] **class BacktestResult**
- [ ] **def BacktestResult.hit_rate(self)**
- [ ] **class BacktestRiskMonitor**
- [ ] **def BacktestRiskMonitor.__init__(self, initial_capital)**
- [ ] **def BacktestRiskMonitor.update(self, current_value)**
    - *Calls*: `max`, `self.portfolio_values.append`
- [ ] **def BacktestRiskMonitor.record_trade(self, trade)**
    - *Calls*: `self.trades.append`
- [ ] **def BacktestRiskMonitor.get_total_return(self)**
- [ ] **def BacktestRiskMonitor.get_summary(self)**
    - *Calls*: `len`, `round`, `self.get_total_return`, `t.get`

### runner.py

- [ ] **class WeeklyBacktester**
- [ ] **def WeeklyBacktester.__init__(self, start_date, end_date, base_url)**
    - *Calls*: `BacktestAPIClient`, `BacktestConfigLoader`, `BacktestRiskMonitor`, `PortfolioControlsService`, `self.config_loader.fetch`
- [ ] **def WeeklyBacktester.get_week_mondays(self)**
    - *Calls*: `current.weekday`, `mondays.append`, `timedelta`
- [ ] **def WeeklyBacktester.calculate_position_size(self, atr, current_price)**
    - *Calls*: `int`, `max`, `round`
- [ ] **def WeeklyBacktester.should_trigger_stop_loss(self, current_price, effective_stop)**
- [ ] **def WeeklyBacktester.should_exit_score_degradation(self, score)**
- [ ] **def WeeklyBacktester.should_swap(self, incumbent_score, challenger_score)**
- [ ] **def WeeklyBacktester.calculate_portfolio_value(self, current_prices)**
    - *Calls*: `current_prices.get`, `self.positions.values`, `sum`
- [ ] **def WeeklyBacktester.execute_sell(self, symbol, current_price, week_date, reason)**
    - *Calls*: `calculate_capital_gains_tax`, `calculate_round_trip_cost`, `costs.get`, `round`, `self.risk_monitor.record_trade`, `tax_info.get`, `week_date.isoformat`
- [ ] **def WeeklyBacktester.execute_buy(self, symbol, price, score, atr, week_date, reason)**
    - *Calls*: `PositionSizingConfig`, `Position`, `calculate_initial_stop_loss`, `calculate_round_trip_cost`, `costs.get`, `logger.warning`, `round`, `self.calculate_position_size`, `week_date.isoformat`
- [ ] **def WeeklyBacktester.rebalance_portfolio(self, week_date, top_rankings, score_lookup, price_lookup)**
    - *Calls*: `actions.append`, `calculate_effective_stop`, `challengers.pop`, `len`, `list`, `price_lookup.get`, `score_lookup.get`, `self.api.get_indicator`, `self.execute_buy`, `self.execute_sell`, `self.positions.items`, `self.positions.keys`, `self.should_exit_score_degradation`, `self.should_swap`, `self.should_trigger_stop_loss`, `set`, `week_date.isoformat`
- [ ] **def WeeklyBacktester.run(self)**
    - *Calls*: `BacktestResult`, `DatabaseManager.clear_backtest_db`, `DatabaseManager.get_backtest_session`, `DatabaseManager.init_backtest_db`, `asdict`, `current_app._get_current_object`, `logger.info`, `logger.warning`, `self._persist_weekly_result`, `self.api.get_close_price`, `self.api.get_top_rankings`, `self.calculate_portfolio_value`, `self.get_week_mondays`, `self.portfolio_controls.check_drawdown_status`, `self.positions.values`, `self.rebalance_portfolio`, `self.risk_monitor.get_total_return`, `self.risk_monitor.update`, `self.weekly_results.append`
- [ ] **def WeeklyBacktester._persist_weekly_result(self, week_date, actions, portfolio_value)**
    - *Calls*: `InvestmentRepository.bulk_insert_actions`, `InvestmentRepository.bulk_insert_holdings`, `InvestmentRepository.get_summary`, `InvestmentRepository.insert_summary`, `action.get`, `action_records.append`, `action_records.extend`, `buy.get`, `holding_records.append`, `lower`, `round`, `self.positions.values`, `sell.get`
- [ ] **def WeeklyBacktester.get_summary(self)**
    - *Calls*: `round`, `self.risk_monitor.get_summary`
- [ ] **def run_backtest(start_date, end_date, base_url)**
    - *Calls*: `WeeklyBacktester`, `backtester.get_summary`, `backtester.run`

## src\models


### indicators.py

- [ ] **class IndicatorsModel**
- [ ] **def IndicatorsModel.__repr__(self)**

### instruments.py

- [ ] **class InstrumentModel**
- [ ] **def InstrumentModel.__repr__(self)**

### investment.py

- [ ] **class InvestmentHoldingsModel**
- [ ] **def InvestmentHoldingsModel.risk(self)**
    - *Calls*: `float`, `max`, `round`
- [ ] **def InvestmentHoldingsModel.__repr__(self)**
- [ ] **def InvestmentHoldingsModel.to_dict(self)**
    - *Calls*: `getattr`
- [ ] **class InvestmentSummaryModel**
- [ ] **def InvestmentSummaryModel.__repr__(self)**
- [ ] **def InvestmentSummaryModel.to_dict(self)**
    - *Calls*: `getattr`

### marketdata.py

- [ ] **class MarketDataModel**
- [ ] **def MarketDataModel.__repr__(self)**

### master.py

- [ ] **class MasterModel**
- [ ] **def MasterModel.__repr__(self)**

### percentile.py

- [ ] **class PercentileModel**

### ranking.py

- [ ] **class RankingModel**
- [ ] **def RankingModel.__repr__(self)**

### risk_config.py

- [ ] **class RiskConfigModel**
- [ ] **def RiskConfigModel.__repr__(self)**

### score.py

- [ ] **class ScoreModel**
- [ ] **def ScoreModel.__repr__(self)**

## src\repositories

### __init__.py (No definitions)

### actions_repository.py

- [ ] **class ActionsRepository**
- [ ] **def ActionsRepository._get_session(session)**
- [ ] **def ActionsRepository.get_action_dates(session)**
    - *Calls*: `ActionsModel.working_date.desc`, `ActionsRepository._get_session`, `all`, `distinct`, `order_by`, `sess.query`
- [ ] **def ActionsRepository.get_actions(working_date, session)**
    - *Calls*: `ActionsRepository._get_session`, `all`, `filter`, `func.max`, `scalar`, `sess.query`
- [ ] **def ActionsRepository.get_action_by_symbol(symbol, working_date, session)**
    - *Calls*: `ActionsRepository._get_session`, `filter`, `first`, `func.max`, `scalar`, `sess.query`
- [ ] **def ActionsRepository.bulk_insert_actions(actions, session)**
    - *Calls*: `ActionsRepository._get_session`, `delete`, `filter`, `logger.error`, `sess.bulk_insert_mappings`, `sess.commit`, `sess.query`, `sess.rollback`
- [ ] **def ActionsRepository.check_other_pending_actions(working_date, session)**
    - *Calls*: `ActionsRepository._get_session`, `all`, `filter`, `sess.query`
- [ ] **def ActionsRepository.update_action(action_data, session)**
    - *Calls*: `ActionsRepository._get_session`, `action_data.items`, `filter`, `first`, `hasattr`, `logger.error`, `logger.warning`, `sess.commit`, `sess.query`, `sess.rollback`, `setattr`
- [ ] **def ActionsRepository.delete_all_actions(session)**
    - *Calls*: `ActionsRepository._get_session`, `delete`, `logger.error`, `sess.commit`, `sess.query`, `sess.rollback`

### config_repository.py

- [ ] **class ConfigRepository**
- [ ] **def ConfigRepository.get_config(strategy_name)**
    - *Calls*: `RiskConfigModel.query.filter`, `first`
- [ ] **def ConfigRepository.post_config(config_data)**
    - *Calls*: `RiskConfigModel`, `db.session.add`, `db.session.commit`
- [ ] **def ConfigRepository.update_config(config_data)**
    - *Calls*: `RiskConfigModel.query.first`, `config_data.items`, `db.session.commit`, `setattr`

### indicators_repository.py

- [ ] **class IndicatorsRepository**
- [ ] **def IndicatorsRepository.bulk_insert(indicator_data)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`
- [ ] **def IndicatorsRepository.query(filter_data)**
    - *Calls*: `and_`, `date`, `datetime.now`, `filter_data.get`, `instrument_filter.append`, `or_`, `query.all`, `query.filter`
- [ ] **def IndicatorsRepository.get_latest_date_for_all()**
    - *Calls*: `db.session.query`, `func.max`, `group_by`, `label`, `query.all`
- [ ] **def IndicatorsRepository.get_latest_date_by_symbol(tradingsymbol)**
    - *Calls*: `IndicatorsModel.date.desc`, `IndicatorsModel.query.filter`, `first`, `query.order_by`
- [ ] **def IndicatorsRepository.get_indicators_for_all_stocks(date_range)**
    - *Calls*: `and_`, `date_filter.append`, `query.all`, `query.filter`
- [ ] **def IndicatorsRepository.delete_by_tradingsymbol(tradingsymbol)**
    - *Calls*: `IndicatorsModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`
- [ ] **def IndicatorsRepository.get_indicator_by_tradingsymbol(indicator, tradingsymbol, date)**
    - *Calls*: `IndicatorsModel.date.desc`, `IndicatorsModel.query.filter`, `first`, `getattr`, `query.filter`, `query.order_by`, `query.with_entities`
- [ ] **def IndicatorsRepository.delete_after_date(date)**
    - *Calls*: `IndicatorsModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`

### instruments_repository.py

- [ ] **class InstrumentsRepository**
- [ ] **def InstrumentsRepository.get_all_instruments()**
    - *Calls*: `InstrumentModel.query.all`
- [ ] **def InstrumentsRepository.bulk_insert(instrument_data)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`
- [ ] **def InstrumentsRepository.delete_all()**
    - *Calls*: `InstrumentModel.query.delete`, `db.session.commit`, `db.session.rollback`
- [ ] **def InstrumentsRepository.get_by_token(instrument_token)**
    - *Calls*: `InstrumentModel.query.get`
- [ ] **def InstrumentsRepository.get_by_symbol(tradingsymbol)**
    - *Calls*: `InstrumentModel.query.filter_by`, `first`
- [ ] **def InstrumentsRepository.update_instrument(instrument_token, instrument_data)**
    - *Calls*: `InstrumentModel.query.get`, `db.session.commit`, `db.session.rollback`, `instrument_data.items`, `setattr`

### investment_repository.py

- [ ] **class InvestmentRepository**
- [ ] **def InvestmentRepository._get_session(session)**
- [ ] **def InvestmentRepository.get_holdings_dates(session)**
    - *Calls*: `InvestmentHoldingsModel.working_date.desc`, `InvestmentRepository._get_session`, `all`, `distinct`, `order_by`, `sess.query`
- [ ] **def InvestmentRepository.get_holdings(working_date, session)**
    - *Calls*: `InvestmentRepository._get_session`, `all`, `filter`, `func.max`, `scalar`, `sess.query`
- [ ] **def InvestmentRepository.get_holdings_by_symbol(symbol, working_date, session)**
    - *Calls*: `InvestmentRepository._get_session`, `filter`, `first`, `func.max`, `scalar`, `sess.query`
- [ ] **def InvestmentRepository.get_summary(working_date, session)**
    - *Calls*: `InvestmentRepository._get_session`, `filter`, `first`, `func.max`, `scalar`, `sess.query`
- [ ] **def InvestmentRepository.bulk_insert_holdings(holdings, session)**
    - *Calls*: `InvestmentRepository._get_session`, `delete`, `filter`, `logger.error`, `sess.bulk_insert_mappings`, `sess.commit`, `sess.query`, `sess.rollback`
- [ ] **def InvestmentRepository.insert_summary(summary, session)**
    - *Calls*: `InvestmentRepository._get_session`, `InvestmentSummaryModel`, `delete`, `filter`, `logger.error`, `sess.add`, `sess.commit`, `sess.query`, `sess.rollback`
- [ ] **def InvestmentRepository.delete_holdings(working_date, session)**
    - *Calls*: `InvestmentRepository._get_session`, `delete`, `filter`, `logger.error`, `sess.commit`, `sess.query`, `sess.rollback`
- [ ] **def InvestmentRepository.delete_summary(working_date, session)**
    - *Calls*: `InvestmentRepository._get_session`, `delete`, `filter`, `logger.error`, `sess.commit`, `sess.query`, `sess.rollback`
- [ ] **def InvestmentRepository.delete_all_holdings(session)**
    - *Calls*: `InvestmentRepository._get_session`, `delete`, `logger.error`, `sess.commit`, `sess.query`, `sess.rollback`
- [ ] **def InvestmentRepository.delete_all_summary(session)**
    - *Calls*: `InvestmentRepository._get_session`, `delete`, `logger.error`, `sess.commit`, `sess.query`, `sess.rollback`

### marketdata_repository.py

- [ ] **class MarketDataRepository**
- [ ] **def MarketDataRepository.bulk_insert(market_data)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`
- [ ] **def MarketDataRepository.query(filter_data)**
    - *Calls*: `and_`, `date`, `datetime.now`, `filter_data.get`, `instrument_filter.append`, `or_`, `query.all`, `query.filter`
- [ ] **def MarketDataRepository.get_latest_date_for_all()**
    - *Calls*: `db.session.query`, `func.max`, `group_by`, `label`, `query.all`
- [ ] **def MarketDataRepository.get_latest_date_by_symbol(tradingsymbol)**
    - *Calls*: `MarketDataModel.date.desc`, `MarketDataModel.query.filter`, `first`, `query.order_by`
- [ ] **def MarketDataRepository.get_prices_for_all_stocks(date_range)**
    - *Calls*: `and_`, `date_filter.append`, `query.all`, `query.filter`
- [ ] **def MarketDataRepository.delete_by_tradingsymbol(tradingsymbol)**
    - *Calls*: `MarketDataModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`
- [ ] **def MarketDataRepository.get_max_date_from_table()**
    - *Calls*: `db.session.query`, `func.max`, `scalar`
- [ ] **def MarketDataRepository.get_min_date_from_table()**
    - *Calls*: `db.session.query`, `func.min`, `scalar`
- [ ] **def MarketDataRepository.get_marketdata_next_day(tradingsymbol, date)**
    - *Calls*: `MarketDataModel.date.asc`, `MarketDataModel.query.filter`, `date`, `datetime.now`, `first`, `order_by`
- [ ] **def MarketDataRepository.get_marketdata_by_trading_symbol(tradingsymbol, date)**
    - *Calls*: `MarketDataModel.date.asc`, `MarketDataModel.query.filter`, `first`, `query.order_by`
- [ ] **def MarketDataRepository.delete_after_date(date)**
    - *Calls*: `MarketDataModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`

### master_repository.py

- [ ] **class MasterRepository**
- [ ] **def MasterRepository.delete_all()**
    - *Calls*: `MasterModel.query.delete`, `db.session.commit`, `db.session.rollback`, `logger.error`
- [ ] **def MasterRepository.bulk_insert(master_data)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`, `logger.error`

### percentile_repository.py

- [ ] **class PercentileRepository**
- [ ] **def PercentileRepository.bulk_insert(percentile_records)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`, `logger.error`
- [ ] **def PercentileRepository.delete(percentile_date)**
    - *Calls*: `db.session.commit`, `db.session.query`, `db.session.rollback`, `delete`, `filter`, `logger.error`
- [ ] **def PercentileRepository.get_max_percentile_date()**
    - *Calls*: `PercentileModel.percentile_date.desc`, `PercentileModel.query.order_by`, `first`
- [ ] **def PercentileRepository.get_top_n_by_date(n, date)**
    - *Calls*: `PercentileModel.query.filter`, `all`, `db.func.max`, `db.session.query`, `limit`, `scalar`
- [ ] **def PercentileRepository.get_percentiles_by_date(percentile_date)**
    - *Calls*: `PercentileModel.query.filter`, `all`
- [ ] **def PercentileRepository.get_latest_by_symbol(symbol)**
    - *Calls*: `PercentileModel.percentile_date.desc`, `PercentileModel.query.filter`, `first`, `order_by`
- [ ] **def PercentileRepository.get_by_date_and_symbol(percentile_date, symbol)**
    - *Calls*: `PercentileModel.query.filter`, `all`
- [ ] **def PercentileRepository.delete_by_tradingsymbol(tradingsymbol)**
    - *Calls*: `PercentileModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`
- [ ] **def PercentileRepository.delete_after_date(date)**
    - *Calls*: `PercentileModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`

### ranking_repository.py

- [ ] **class RankingRepository**
- [ ] **def RankingRepository.bulk_insert(ranking_records)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`, `logger.error`
- [ ] **def RankingRepository.delete(ranking_date)**
    - *Calls*: `db.session.commit`, `db.session.query`, `db.session.rollback`, `delete`, `filter`, `logger.error`
- [ ] **def RankingRepository.get_max_ranking_date()**
    - *Calls*: `RankingModel.query.order_by`, `RankingModel.ranking_date.desc`, `first`
- [ ] **def RankingRepository.get_top_n_by_date(n, date)**
    - *Calls*: `RankingModel.composite_score.desc`, `RankingModel.query.filter`, `all`, `db.func.max`, `db.session.query`, `limit`, `order_by`, `scalar`
- [ ] **def RankingRepository.get_rankings_by_date(ranking_date)**
    - *Calls*: `RankingModel.query.filter`, `all`
- [ ] **def RankingRepository.get_latest_rank_by_symbol(symbol)**
    - *Calls*: `RankingModel.query.filter`, `RankingModel.ranking_date.desc`, `first`, `order_by`
- [ ] **def RankingRepository.get_rankings_by_date_and_symbol(ranking_date, symbol)**
    - *Calls*: `RankingModel.composite_score.desc`, `RankingModel.query.filter`, `first`, `order_by`

### score_repository.py

- [ ] **class ScoreRepository**
- [ ] **def ScoreRepository.bulk_insert(score_records)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`, `logger.error`
- [ ] **def ScoreRepository.delete_all()**
    - *Calls*: `db.session.commit`, `db.session.query`, `db.session.rollback`, `delete`, `logger.error`
- [ ] **def ScoreRepository.get_max_score_date()**
    - *Calls*: `ScoreModel.query.order_by`, `ScoreModel.score_date.desc`, `first`
- [ ] **def ScoreRepository.delete_after_date(date)**
    - *Calls*: `ScoreModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`
- [ ] **def ScoreRepository.bulk_insert_ranking(ranking_records)**
    - *Calls*: `db.session.bulk_insert_mappings`, `db.session.commit`, `db.session.rollback`, `logger.error`
- [ ] **def ScoreRepository.delete_all_ranking()**
    - *Calls*: `db.session.commit`, `db.session.query`, `db.session.rollback`, `delete`, `logger.error`
- [ ] **def ScoreRepository.get_max_ranking_date()**
    - *Calls*: `RankingModel.query.order_by`, `RankingModel.ranking_date.desc`, `first`
- [ ] **def ScoreRepository.get_top_n_by_date(n, ranking_date)**
    - *Calls*: `RankingModel.query.filter`, `RankingModel.rank.asc`, `all`, `db.func.max`, `db.session.query`, `limit`, `order_by`, `scalar`
- [ ] **def ScoreRepository.get_by_symbol(symbol, ranking_date)**
    - *Calls*: `RankingModel.query.filter`, `RankingModel.ranking_date.desc`, `first`, `order_by`
- [ ] **def ScoreRepository.get_rankings_after_date(after_date)**
    - *Calls*: `RankingModel.query.filter`, `all`, `order_by`
- [ ] **def ScoreRepository.get_all_rankings()**
    - *Calls*: `RankingModel.query.order_by`, `all`
- [ ] **def ScoreRepository.get_rankings_by_date(ranking_date)**
    - *Calls*: `RankingModel.query.filter`, `RankingModel.rank.asc`, `all`, `order_by`
- [ ] **def ScoreRepository.get_distinct_ranking_dates()**
    - *Calls*: `all`, `db.session.query`, `distinct`, `order_by`
- [ ] **def ScoreRepository.get_scores_in_date_range(start_date, end_date)**
    - *Calls*: `ScoreModel.query.filter`, `all`
- [ ] **def ScoreRepository.delete_ranking_after_date(date)**
    - *Calls*: `RankingModel.query.filter`, `db.session.commit`, `db.session.rollback`, `delete`

## src\schemas

### __init__.py (No definitions)

### actions.py

- [ ] **class ActionDateSchema**
- [ ] **class ActionQuerySchema**
- [ ] **class ActionSchema**
- [ ] **class ActionUpdateSchema**

### app.py

- [ ] **class CleanupQuerySchema**

### backtest.py

- [ ] **class BacktestInputSchema**

### indicators.py

- [ ] **class IndicatorsSchema**
- [ ] **class IndicatorSearchSchema**

### init_app.py

- [ ] **class InitResponseSchema**

### instruments.py

- [ ] **class InstrumentSchema**
- [ ] **class MessageSchema**

### investment.py

- [ ] **class HoldingDateSchema**
- [ ] **class HoldingSchema**
- [ ] **class SummarySchema**

### marketdata.py

- [ ] **class MarketDataSchema**
- [ ] **class MarketDataQuerySchema**
- [ ] **def MarketDataQuerySchema.validate_instrument(self, data)**
    - *Calls*: `ValidationError`
- [ ] **class MaxDateSchema**
- [ ] **class LatestMarketDataQuerySchema**
- [ ] **def LatestMarketDataQuerySchema.validate_instrument(self, data)**
    - *Calls*: `ValidationError`

### percentile.py

- [ ] **class PercentileSchema**
- [ ] **class PercentileAllSchema**

### ranking.py

- [ ] **class RankingSchema**
- [ ] **class TopNSchema**

### risk_config.py

- [ ] **class RiskConfigSchema**

### score.py

- [ ] **class ScoreSchema**

## src\services

### __init__.py (No definitions)

### actions_service.py

- [ ] **class ActionsService**
- [ ] **def ActionsService.get_parameters(cls)**
    - *Calls*: `ConfigRepository`, `config.get_config`
- [ ] **def ActionsService.generate_actions(working_date)**
    - *Calls*: `ActionsService.buy_action`, `ActionsService.fetch_low`, `ActionsService.get_parameters`, `ActionsService.sell_action`, `ValueError`, `current_holdings.pop`, `investment.bulk_insert_actions`, `investment.check_other_pending_actions`, `investment.get_holdings`, `len`, `new_actions.append`, `ranking.get_rankings_by_date_and_symbol`, `ranking.get_top_n_by_date`, `top_n.pop`
- [ ] **def ActionsService.approve_all_actions(working_date)**
    - *Calls*: `ValueError`, `investment.get_actions`, `investment.get_holdings_by_symbol`, `investment.update_action`, `len`, `marketdata.get_marketdata_next_day`
- [ ] **def ActionsService.process_actions(working_date)**
    - *Calls*: `ActionsService.buy_holding`, `ActionsService.get_summary`, `ActionsService.sell_holding`, `ActionsService.update_holding`, `buy_symbols.append`, `date`, `holdings.pop`, `investment.bulk_insert_holdings`, `investment.delete_holdings`, `investment.delete_summary`, `investment.get_actions`, `investment.get_holdings`, `investment.insert_summary`, `len`, `logger.warning`, `sell_symbols.append`, `week_holdings.append`
- [ ] **def ActionsService.get_summary(week_holdings, sold)**
    - *Calls*: `ActionsService.get_parameters`, `Decimal`, `float`, `investment.get_summary`, `pd.DataFrame`, `round`, `sum`
- [ ] **def ActionsService.fetch_low(symbol, working_date)**
    - *Calls*: `ValueError`, `marketdata.query`, `timedelta`
- [ ] **def ActionsService.buy_action(symbol, working_date, reason)**
    - *Calls*: `ActionsService.get_parameters`, `Decimal`, `ValueError`, `indicators.get_indicator_by_tradingsymbol`, `investment.get_summary`, `marketdata.get_marketdata_by_trading_symbol`, `math.floor`, `round`
- [ ] **def ActionsService.sell_action(symbol, working_date, units, reason)**
    - *Calls*: `ValueError`, `marketdata.get_marketdata_by_trading_symbol`
- [ ] **def ActionsService.sell_holding(symbol)**
    - *Calls*: `investment.get_action_by_symbol`
- [ ] **def ActionsService.buy_holding(symbol)**
    - *Calls*: `ActionsService.get_parameters`, `Decimal`, `indicators.get_indicator_by_tradingsymbol`, `investment.get_action_by_symbol`, `ranking.get_rankings_by_date_and_symbol`, `round`, `str`
- [ ] **def ActionsService.update_holding(symbol, working_date)**
    - *Calls*: `ActionsService.get_parameters`, `Decimal`, `indicators.get_indicator_by_tradingsymbol`, `investment.get_holdings_by_symbol`, `marketdata.get_marketdata_by_trading_symbol`, `ranking.get_rankings_by_date_and_symbol`, `round`, `str`

### factors_service.py

- [ ] **class FactorsService**
- [ ] **def FactorsService.__init__(self)**
    - *Calls*: `GoldilocksConfig`, `PenaltyBoxConfig`, `RSIRegimeConfig`, `Strategy1Parameters`
- [ ] **def FactorsService.calculate_trend_factor(self, close, ema_50, ema_200)**
    - *Calls*: `astype`, `dist_200.apply`, `ema_50.shift`, `ema_slope.clip`
- [ ] **def FactorsService._goldilocks_score(self, distance)**
    - *Calls*: `max`
- [ ] **def FactorsService.calculate_momentum_factor(self, rsi_smooth, ppo, roc_60, roc_125)**
    - *Calls*: `clip`, `ppo.clip`, `rsi_smooth.apply`
- [ ] **def FactorsService._rsi_regime_score(self, rsi)**
    - *Calls*: `max`
- [ ] **def FactorsService.calculate_risk_efficiency_factor(self, roc_20, atr, close, atr_spike)**
    - *Calls*: `astype`, `atr_pct.replace`, `risk_adj.clip`
- [ ] **def FactorsService.calculate_volume_factor(self, rvol, vol_price_corr)**
    - *Calls*: `rvol.clip`, `vol_price_corr.clip`
- [ ] **def FactorsService.calculate_structure_factor(self, percent_b, bandwidth)**
    - *Calls*: `bandwidth.pct_change`, `bw_change.clip`, `fillna`, `percent_b.apply`
- [ ] **def FactorsService._b_score(self, b_val)**
    - *Calls*: `max`, `pd.isna`
- [ ] **def FactorsService.calculate_all_factors(self, df)**
    - *Calls*: `df.copy`, `self.calculate_momentum_factor`, `self.calculate_risk_efficiency_factor`, `self.calculate_structure_factor`, `self.calculate_trend_factor`, `self.calculate_volume_factor`

### indicators_service.py

- [ ] **class IndicatorsService**
- [ ] **def IndicatorsService.calculate_volume_price_correlation(df_close, df_volume, lookback)**
    - *Calls*: `corr`, `df_close.pct_change`, `price_change.rolling`
- [ ] **def IndicatorsService.calculate_percent_b(df_close, df_upper, df_lower)**
- [ ] **def IndicatorsService.calculate_ema_slope(ema, lookback)**
    - *Calls*: `ema.shift`
- [ ] **def IndicatorsService.calculate_distance_from_ema(df_close, ema)**
- [ ] **def IndicatorsService.calculate_atr_spike(atr, lookback)**
    - *Calls*: `atr.rolling`, `mean`
- [ ] **def IndicatorsService.apply_study(df, last_ind_date)**
    - *Calls*: `df.ta.study`, `timedelta`
- [ ] **def IndicatorsService._calculate_derived_indicators(self, df)**
    - *Calls*: `self.calculate_atr_spike`, `self.calculate_distance_from_ema`, `self.calculate_ema_slope`, `self.calculate_percent_b`, `self.calculate_volume_price_correlation`
- [ ] **def IndicatorsService.calculate_indicators(self)**
    - *Calls*: `calc_start_date.date`, `df_for_ind.set_index`, `df_for_ind.sort_index`, `enumerate`, `getattr`, `ind_df.columns.str.lower`, `ind_df.drop`, `ind_df.reset_index`, `ind_df_filtered.to_dict`, `indicators_repo.bulk_insert`, `indicators_repo.get_latest_date_by_symbol`, `instr_repo.get_all_instruments`, `len`, `logger.error`, `logger.info`, `marketdata_repo.get_latest_date_by_symbol`, `marketdata_repo.query`, `normalize`, `pd.DataFrame`, `pd.Timedelta`, `pd.Timestamp.now`, `pd.to_datetime`, `self._calculate_derived_indicators`, `self.apply_study`, `str.replace`, `str`, `timedelta`, `yesterday.date`

### init_service.py

- [ ] **class InitService**
- [ ] **def InitService.__init__(self)**
- [ ] **def InitService.initialize_app(self)**
    - *Calls*: `df.apply`, `df.to_csv`, `logger.info`, `self.fetch_and_merge_csvs`, `self.fetch_yfinance_data`, `self.filter_stocks`, `self.get_instruments`, `self.push_to_master`, `self.sync_with_kite`
- [ ] **def InitService.fetch_and_merge_csvs(self)**
    - *Calls*: `FileNotFoundError`, `astype`, `df_bse.rename`, `df_bse.reset_index`, `df_consolidated.drop`, `df_nse.rename`, `fillna`, `len`, `os.path.exists`, `pd.merge`, `pd.read_csv`, `replace`, `str.contains`, `str.startswith`, `upper`, `x.strip`
- [ ] **def InitService.generate_yfinance_tickers(row)**
    - *Calls*: `pd.notna`, `tickers.append`
- [ ] **def InitService.fetch_yfinance_data(df)**
    - *Calls*: `df.iterrows`, `json.dumps`, `len`, `logger.error`, `logger.info`, `str`, `time.sleep`, `yf.get_stock_info`, `yfinance_info.get`
- [ ] **def InitService.push_to_master(df)**
    - *Calls*: `df.columns.str.lower`, `df.to_json`, `df.where`, `json.loads`, `logger.error`, `master_repo.bulk_insert`, `master_repo.delete_all`, `pd.notnull`, `str`
- [ ] **def InitService.filter_stocks(df)**
    - *Calls*: `len`, `logger.info`, `pd.to_numeric`
- [ ] **def InitService.get_instruments()**
    - *Calls*: `len`, `logger.info`, `pd.read_csv`
- [ ] **def InitService.sync_with_kite(self, df, instruments_df)**
    - *Calls*: `astype`, `copy`, `drop_duplicates`, `final_instruments.merge`, `final_instruments.rename`, `final_instruments.to_json`, `instr_repo.bulk_insert`, `instr_repo.delete_all`, `instruments_df.copy`, `isin`, `json.loads`, `kite_nse_hyphen.sort_values`, `len`, `logger.error`, `logger.info`, `pd.concat`, `rename`, `set`, `str.split`

### marketdata_service.py

- [ ] **class MarketDataService**
- [ ] **def MarketDataService.__init__(self)**
    - *Calls*: `KiteAdaptor`
- [ ] **def MarketDataService.get_latest_data_by_token(self, token, start_date, end_date)**
    - *Calls*: `self.kite_client.fetch_ticker_data`, `self.logger.error`, `self.logger.warning`, `time`
- [ ] **def MarketDataService.update_latest_data_for_all(self, historical, historical_start_date)**
    - *Calls*: `enumerate`, `indicators_repository.delete_by_tradingsymbol`, `instr_repository.get_all_instruments`, `len`, `logger.info`, `logger.warning`, `marketdata_repository.bulk_insert`, `marketdata_repository.delete_by_tradingsymbol`, `marketdata_repository.get_latest_date_by_symbol`, `max`, `normalize`, `pd.DataFrame`, `pd.Timedelta`, `pd.Timestamp.now`, `pd.to_datetime`, `records_df.reset_index`, `records_df.to_dict`, `self.get_historical_data`, `self.get_latest_data_by_token`, `sleep`, `start_date.date`, `time`, `timedelta`
- [ ] **def MarketDataService.get_historical_data(self, ticker, start_date)**
    - *Calls*: `all_records.extend`, `current_end.date`, `current_start.date`, `max`, `normalize`, `pd.Timedelta`, `pd.Timestamp.now`, `pd.to_datetime`, `self.kite_client.fetch_ticker_data`, `self.logger.error`, `self.logger.info`, `self.logger.warning`, `sleep`, `target_start_date.date`, `time`

### percentile_service.py

- [ ] **class PercentileService**
- [ ] **def PercentileService.__init__(self)**
    - *Calls*: `StrategyParams`
- [ ] **def PercentileService._calculate_percentile_ranks(metrics_df)**
    - *Calls*: `percentile_rank`, `rank_cols.items`, `score_percent_b`, `score_rsi_regime`, `score_trend_extension`
- [ ] **def PercentileService._calculate_weighted_composite(self, metrics_df)**
    - *Calls*: `fillna`, `metrics_df.get`
- [ ] **def PercentileService._apply_universe_penalties(self, metrics_df)**
    - *Calls*: `fillna`, `shift`
- [ ] **def PercentileService.calculate_composite_score(self, metrics_df)**
    - *Calls*: `self._calculate_percentile_ranks`
- [ ] **def PercentileService.query_to_dict(results)**
    - *Calls*: `getattr`
- [ ] **def PercentileService.generate_percentile(self, date)**
    - *Calls*: `format`, `indicators_repo.get_indicators_for_all_stocks`, `len`, `logger.error`, `logger.info`, `marketdata_repo.get_max_date_from_table`, `marketdata_repo.get_prices_for_all_stocks`, `pd.DataFrame`, `pd.merge`, `percentile_repo.bulk_insert`, `percentile_repo.delete`, `ranked_df.to_dict`, `self.calculate_composite_score`, `self.query_to_dict`
- [ ] **def PercentileService.backfill_percentiles(self)**
    - *Calls*: `isinstance`, `marketdata_repo.get_min_date_from_table`, `normalize`, `pd.Timedelta`, `pd.Timestamp.now`, `pd.Timestamp`, `percentile_repo.get_max_percentile_date`, `self.generate_percentile`

### portfolio_controls_service.py

- [ ] **class PortfolioControlsService**
- [ ] **def PortfolioControlsService.__init__(self, config)**
    - *Calls*: `PortfolioControlConfig`
- [ ] **def PortfolioControlsService.check_drawdown_status(self, current_value, peak_value)**
    - *Calls*: `round`
- [ ] **def PortfolioControlsService.check_sector_concentration(self, holdings, sector_column)**
    - *Calls*: `breached.to_dict`, `holdings.groupby`, `len`, `sector_weights.to_dict`, `sum`
- [ ] **def PortfolioControlsService.apply_all_controls(self, portfolio_value, peak_value, holdings)**
    - *Calls*: `drawdown.get`, `round`, `self.check_drawdown_status`, `self.check_sector_concentration`

### ranking_service.py

- [ ] **def get_friday(d)**
    - *Calls*: `d.weekday`, `timedelta`
- [ ] **class RankingService**
- [ ] **def RankingService.generate_rankings(self)**
    - *Calls*: `all_ranking_records.extend`, `all`, `db.session.query`, `df.groupby`, `distinct`, `get_friday`, `len`, `logger.info`, `mean`, `order_by`, `pd.DataFrame`, `range`, `reset_index`, `score_repo.bulk_insert_ranking`, `score_repo.get_max_ranking_date`, `score_repo.get_max_score_date`, `score_repo.get_scores_in_date_range`, `timedelta`, `weekly_avg.sort_values`, `weekly_avg.to_dict`
- [ ] **def RankingService.recalculate_all_rankings(self)**
    - *Calls*: `logger.info`, `score_repo.delete_all_ranking`, `self.generate_rankings`

### score_service.py

- [ ] **class ScoreService**
- [ ] **def ScoreService.__init__(self)**
    - *Calls*: `Strategy1Parameters`
- [ ] **def ScoreService._calculate_composite_for_df(self, df)**
    - *Calls*: `astype`, `fillna`
- [ ] **def ScoreService.generate_composite_scores(self)**
    - *Calls*: `all`, `copy`, `db.session.query`, `distinct`, `enumerate`, `getattr`, `len`, `logger.info`, `order_by`, `pd.DataFrame`, `percentile_repo.get_percentiles_by_date`, `score_records.rename`, `score_records.to_dict`, `score_repo.bulk_insert`, `score_repo.get_max_score_date`, `self._calculate_composite_for_df`
- [ ] **def ScoreService.recalculate_all_scores(self)**
    - *Calls*: `logger.info`, `score_repo.delete_all`, `self.generate_composite_scores`

## src\utils

### __init__.py (No definitions)

### database_manager.py

- [ ] **class DatabaseManager**
- [ ] **def DatabaseManager.get_session(cls, bind_key)**
    - *Calls*: `db.get_engine`, `scoped_session`, `sessionmaker`
- [ ] **def DatabaseManager.get_backtest_session(cls)**
    - *Calls*: `cls.get_session`
- [ ] **def DatabaseManager.init_backtest_db(cls, app)**
    - *Calls*: `ActionsModel.__table__.create`, `InvestmentHoldingsModel.__table__.create`, `InvestmentSummaryModel.__table__.create`, `app.app_context`, `db.get_engine`, `logger.info`
- [ ] **def DatabaseManager.clear_backtest_db(cls, app)**
    - *Calls*: `app.app_context`, `cls.get_backtest_session`, `delete`, `logger.error`, `logger.info`, `session.commit`, `session.query`, `session.rollback`
- [ ] **def DatabaseManager.close_sessions(cls)**
    - *Calls*: `cls._sessions.clear`, `cls._sessions.values`, `session.remove`

### finance_utils.py

- [ ] **def calculate_xirr(cash_flows, guess)**
    - *Calls*: `all`, `cash_flows.sort`, `optimize.newton`
- [ ] **def npv(rate)**

### penalty_box_utils.py

- [ ] **def apply_penalty_box(df, config)**
    - *Calls*: `PenaltyBoxConfig`, `df.copy`, `pd.Series`
- [ ] **def check_penalty_status(close, ema_200, atr_spike, avg_turnover, config)**
    - *Calls*: `PenaltyBoxConfig`, `len`, `reasons.append`

### ranking_utils.py

- [ ] **def percentile_rank(series)**
    - *Calls*: `ValueError`, `series.rank`
- [ ] **def z_score_normalize(series, cap_at)**
    - *Calls*: `np.clip`, `pd.Series`, `stats.zscore`
- [ ] **def score_rsi_regime(rsi)**
    - *Calls*: `pd.Series`
- [ ] **def score_trend_extension(dist_200)**
    - *Calls*: `pd.Series`
- [ ] **def score_percent_b(percent_b)**
    - *Calls*: `pd.Series`

### sizing_utils.py

- [ ] **def calculate_position_size(atr, current_price, portfolio_value, avg_daily_volume_value, config)**
    - *Calls*: `PositionSizingConfig`, `constraints.items`, `constraints.values`, `float`, `int`, `max`, `min`, `round`
- [ ] **def calculate_equal_weight_position(portfolio_value, max_positions, current_price)**
    - *Calls*: `ValueError`, `int`, `max`, `round`

### stoploss_utils.py

- [ ] **def calculate_initial_stop_loss(buy_price, atr, stop_multiplier, config)**
    - *Calls*: `PositionSizingConfig`, `max`
- [ ] **def calculate_atr_trailing_stop(current_price, current_atr, stop_multiplier, previous_stop)**
    - *Calls*: `max`
- [ ] **def calculate_trailing_hard_stop(buy_price, current_price, initial_stop, sl_step_percent)**
    - *Calls*: `int`, `min`
- [ ] **def calculate_effective_stop(buy_price, current_price, current_atr, initial_stop, stop_multiplier, sl_step_percent, previous_stop)**
    - *Calls*: `calculate_atr_trailing_stop`, `calculate_trailing_hard_stop`, `min`, `round`

### tax_utils.py

- [ ] **def calculate_capital_gains_tax(purchase_price, current_price, purchase_date, current_date, quantity, config)**
    - *Calls*: `TaxConfig`, `max`, `round`
- [ ] **def should_hold_for_ltcg(purchase_date, current_date, current_score, config)**
    - *Calls*: `TaxConfig`
- [ ] **def calculate_tax_adjusted_cost(purchase_price, current_price, purchase_date, current_date, quantity, switching_cost_pct, config)**
    - *Calls*: `TaxConfig`, `calculate_capital_gains_tax`, `round`

### transaction_costs_utils.py

- [ ] **def calculate_transaction_costs(trade_value, side, config)**
    - *Calls*: `TransactionCostConfig`, `min`, `round`
- [ ] **def calculate_buy_costs(trade_value, config)**
    - *Calls*: `calculate_transaction_costs`
- [ ] **def calculate_sell_costs(trade_value, config)**
    - *Calls*: `calculate_transaction_costs`
- [ ] **def calculate_impact_cost(order_pct_adv, config)**
    - *Calls*: `ImpactCostConfig`
- [ ] **def calculate_round_trip_cost(trade_value, order_pct_adv, tx_config, impact_config)**
    - *Calls*: `calculate_impact_cost`, `calculate_transaction_costs`, `round`

