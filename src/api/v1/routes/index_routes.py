"""
Index Ticker Routes

Uses REST API polling (kite.ohlc) every 30s via a background thread.
This avoids WebSocket conflicts with the portfolio live ticker, since
Kite Connect only allows one WebSocket connection per access token.

─── To add more indices ───────────────────────────────────────────
1. Add entry to INDEX_INSTRUMENTS: {"exchange:tradingsymbol": "Display Name"}
2. Add display name to INDEX_ORDER in static/js/index_ticker.js
──────────────────────────────────────────────────────────────────
"""

import threading
import time
from typing import Dict, Optional

from flask import jsonify
from flask.views import MethodView
from flask_smorest import Blueprint

from adaptors import KiteAdaptor
from config import KITE_CONFIG, setup_logger

logger = setup_logger(name="IndexRoutes")

# ─── ADD MORE INDICES HERE ────────────────────────────────────────
# Format: "EXCHANGE:TRADINGSYMBOL" → "Display Name shown in ticker"
# Common Kite exchange:symbol values for indices:
#   NSE:NIFTY 50, NSE:NIFTY 100, NSE:NIFTY BANK, NSE:NIFTY MIDCAP 50
#   BSE:SENSEX, BSE:BANKEX, NSE:INDIA VIX
INDEX_INSTRUMENTS: Dict[str, str] = {
    "NSE:NIFTY 50":       "NIFTY 50",
    "NSE:NIFTY 100":      "NIFTY 100",
    "NSE:NIFTY BANK":     "NIFTY BANK",
    "BSE:SENSEX":         "SENSEX",
}
# ─────────────────────────────────────────────────────────────────

POLL_INTERVAL_SECS = 30   # how often to refresh via REST

_index_kite: Optional[KiteAdaptor] = None
_index_lock  = threading.Lock()
_index_prices: Dict[str, Dict] = {}
_poll_thread: Optional[threading.Thread] = None
_running = False


def _get_kite() -> KiteAdaptor:
    global _index_kite
    if _index_kite is None:
        _index_kite = KiteAdaptor(KITE_CONFIG, logger)
    return _index_kite


def _fetch_and_cache() -> None:
    """Fetch OHLC for all indices and update the cache."""
    try:
        kite = _get_kite()
        symbols = list(INDEX_INSTRUMENTS.keys())
        ohlc = kite.fetch_ohlc(symbols)

        with _index_lock:
            for key, val in ohlc.items():
                # key may be "NSE:NIFTY 50" or "NSE:NIFTY+50" — match flexibly
                name = INDEX_INSTRUMENTS.get(key)
                if not name:
                    # try alternate spacing
                    for k, v in INDEX_INSTRUMENTS.items():
                        if key.replace("+", " ") == k or k.replace(" ", "+") == key:
                            name = v
                            break
                if not name:
                    continue

                ltp  = val.get("last_price", 0)
                prev = val.get("ohlc", {}).get("close", 0)
                chg  = ((ltp - prev) / prev * 100) if prev else 0.0
                _index_prices[name] = {
                    "last_price": round(ltp, 2),
                    "prev_close": round(prev, 2),
                    "change":     round(chg, 2),
                }

        logger.debug(f"Index prices refreshed: {list(_index_prices.keys())}")
    except Exception as e:
        logger.error(f"Index price fetch failed: {e}")


def _poll_loop() -> None:
    """Background thread: poll REST API every POLL_INTERVAL_SECS."""
    global _running
    while _running:
        _fetch_and_cache()
        time.sleep(POLL_INTERVAL_SECS)


blp = Blueprint(
    "Index", __name__, url_prefix="/api/v1/index",
    description="Market Index Live Prices (REST polling)"
)


@blp.route("/start")
class StartIndexTicker(MethodView):
    @blp.doc(tags=["Index"])
    def post(self):
        """Start background REST polling for index prices."""
        global _poll_thread, _running

        with _index_lock:
            if _running:
                return jsonify({"message": "Index ticker already running", "running": True})

        _running = True
        # Immediate first fetch (blocking, so first /prices call has data)
        _fetch_and_cache()

        _poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="IndexPollThread")
        _poll_thread.start()

        return jsonify({
            "message":  "Index ticker started (REST polling)",
            "running":  True,
            "interval": POLL_INTERVAL_SECS,
            "indices":  list(INDEX_INSTRUMENTS.values()),
        })


@blp.route("/prices")
class IndexPrices(MethodView):
    @blp.doc(tags=["Index"])
    def get(self):
        """Get latest cached index prices."""
        with _index_lock:
            snapshot = dict(_index_prices)
        return jsonify({"prices": snapshot, "running": _running})


@blp.route("/stop")
class StopIndexTicker(MethodView):
    @blp.doc(tags=["Index"])
    def post(self):
        """Stop the index polling thread."""
        global _running
        _running = False
        return jsonify({"message": "Index ticker stopped"})
