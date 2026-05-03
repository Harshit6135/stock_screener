import yfinance as yf

from config import setup_logger

logger = setup_logger(name="YFinanceAdaptor")

# Sentinel strings used to identify HTTP 429 / rate-limit responses from
# yfinance (which surfaces them as plain Python exceptions with these phrases
# in the message text).
_RATE_LIMIT_MARKERS = ("429", "too many requests", "rate limit", "ratelimit")


class RateLimitError(Exception):
    """Raised when yfinance signals an HTTP 429 / rate-limit response."""


class YFinanceAdaptor:

    @staticmethod
    def get_stock_info(tickers_list):
        """Fetch stock info for the first working ticker in *tickers_list*.

        Returns:
            (info_dict, ticker_used, status)  where status is 'Success' or 'Failed'.

        Raises:
            RateLimitError: when any ticker triggers an HTTP 429 / rate-limit
                response so the caller can pause and retry.
        """
        yfinance_info = None
        yfinance_ticker_used = None
        yfinance_status = "Failed"

        for ticker in tickers_list:
            try:
                info = yf.Ticker(ticker).info
                if info and "regularMarketPrice" in info:
                    yfinance_info = info
                    yfinance_ticker_used = ticker
                    yfinance_status = "Success"
                    break
            except Exception as e:
                err_lower = str(e).lower()
                if any(marker in err_lower for marker in _RATE_LIMIT_MARKERS):
                    # Propagate immediately so the service layer can back-off
                    # and retry rather than silently failing the stock.
                    logger.warning(
                        f"HTTP 429 / rate-limit detected for ticker '{ticker}'. "
                        "Propagating RateLimitError to trigger back-off."
                    )
                    raise RateLimitError(str(e))
                logger.error(f"Error fetching {ticker}: {e}")

        return yfinance_info, yfinance_ticker_used, yfinance_status
