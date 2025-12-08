from services.screener_service import ScreenerService

if __name__ == "__main__":
    screener = ScreenerService()
    screener.logger.info("Starting Stock Screener Application")
    screener.run()
