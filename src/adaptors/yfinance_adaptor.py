import json
import yfinance as yf


class YFinanceAdaptor:

    @staticmethod
    def get_stock_info(tickers_list):
        
        yfinance_info = None
        yfinance_ticker_used = None
        yfinance_status = 'Failed'

        for ticker in tickers_list:
            try:
                info = yf.Ticker(ticker).info
                if info and 'regularMarketPrice' in info:
                    yfinance_info = info
                    yfinance_ticker_used = ticker
                    yfinance_status = 'Success'
                    break
            except Exception as e:
                print(e)
                pass
        return yfinance_info, yfinance_ticker_used, yfinance_status
