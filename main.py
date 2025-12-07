from stock_screener.screener import StockScreener

if __name__ == "__main__":
    screener = StockScreener()
    screener.logger.info("Starting Stock Screener Application")
    screener.run()
