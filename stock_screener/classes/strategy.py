from stock_screener.config import CONFIG

class ScreenerStrategy:
    def apply(self, data):
        if not data.get('Data_Found'):
            data['Status'] = "NO DATA"
            data['Summary'] = f"Skipped: {data.get('Issue', 'Unknown Error')}"
            for key in ['Price', 'RSI', 'Bandwidth', 'Trend_OK']:
                data[key] = None
            return data

        trend_ok = (data['Price'] > data['Short_MA']) and (data['Short_MA'] > data['Long_MA'])
        limit = data['Hist_Low_BW'] * (1 + CONFIG["squeeze"]["threshold_pct"])
        squeeze_ok = data['Bandwidth'] <= limit
        stoch_ok = data['Stoch_K'] < CONFIG['stochastic']['overbought']
        squeeze_setup = squeeze_ok and trend_ok and stoch_ok

        macd_ok = data['MACD'] > data['Signal_Line']
        roc_ok = data['ROC'] > 0
        rsi_ok = data['RSI'] > CONFIG["momentum"]["rsi_threshold"]
        rsi_trend_bullish = data['RSI'] > data['RSI_Signal']
        stoch_cross_up = (data['Stoch_K'] > data['Stoch_D'])
        vol_rising = data['Vol_Short'] > data['Vol_Long']

        momentum_setup = (trend_ok
                          and roc_ok
                          and macd_ok
                          and rsi_ok
                          and rsi_trend_bullish
                          and vol_rising
                          and stoch_cross_up)

        if squeeze_setup or momentum_setup:
            if squeeze_setup and momentum_setup:
                setup_type = "SUPER (Squeeze+Vol)"
            elif squeeze_setup:
                setup_type = "Squeeze Play"
            else:
                setup_type = "Momentum Play"
            status = "MATCH"
            summary = "READY! Perfect Setup"
        else:
          reasons = []
          if not trend_ok: reasons.append("Downtrend")
          if not rsi_ok: reasons.append("Low RSI")
          if not squeeze_ok: reasons.append("No Squeeze")
          if not macd_ok: reasons.append("MACD Wait")
          if not vol_rising: reasons.append("Vol Trend Weak")
          status = "FAIL"
          setup_type = "NONE"
          summary = " | ".join(reasons)

        data['Status'] = status
        data['setup_type'] = setup_type
        data['Summary'] = summary
        data['Trend_OK'] = trend_ok
        data['RSI_OK'] = rsi_ok
        data['Squeeze_OK'] = squeeze_ok
        data['MACD_OK'] = macd_ok
        data['vol_rising'] = vol_rising

        return data
