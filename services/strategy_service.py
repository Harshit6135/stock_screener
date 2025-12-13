from config.kite_config import CONFIG

class StrategyService:
    def strategy_momentum_and_squeeze(self, market_data, indicator_data):
        price_check = (market_data['Close'] > indicator_data['ema_50']) and (indicator_data['ema_50'] > indicator_data['ema_200'])
        squeeze_check = indicator_data['bb_bandwidth'] <= (indicator_data['bb_hist_low_bw'] * (1 + CONFIG["squeeze"]["threshold_pct"]))
        rsi_check = indicator_data['rsi_14'] > CONFIG["momentum"]["rsi_threshold"]
        rsi_bullish = indicator_data['rsi_14'] > indicator_data['rsi_signal']
        roc_check = indicator_data['roc_10'] > 0
        macd_check = indicator_data['macd'] > indicator_data['macd_signal']
        stoch_check = indicator_data['stoch_k'] < CONFIG["stochastic"]["overbought"]
        stoch_cross = indicator_data['stoch_k'] > indicator_data['stoch_d']
        vol_check = indicator_data['vol_5'] > indicator_data['vol_20']

        squeeze_setup = squeeze_check and price_check and stoch_check
        momentum_setup = price_check and rsi_check and rsi_bullish and roc_check and macd_check and vol_check and stoch_cross

        if squeeze_setup or momentum_setup:
            if squeeze_setup and momentum_setup:
                setup_type = "SUPER (Squeeze+Momentum)"
            elif squeeze_setup:
                setup_type = "Squeeze Setup"
            else:
                setup_type = "Momentum Setup"
            status = "MATCH"
            summary = "READY! Perfect Setup"
        else:
            status = "FAIL"
            setup_type = "No Setup"
            summary = "SKIP"

        data = {
            "price_check": price_check,
            "squeeze_check": squeeze_check,
            "rsi_check": rsi_check,
            "rsi_bullish": rsi_bullish,
            "roc_check": roc_check,
            "macd_check": macd_check,
            "stoch_check": stoch_check,
            "stoch_cross": stoch_cross,
            "vol_check": vol_check,
            "squeeze_setup": squeeze_setup,
            "momentum_setup": momentum_setup,
            "setup_type": setup_type,
            "status": status,
            "summary": summary
        }

        return data
