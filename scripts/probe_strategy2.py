"""Check Strategy 2 formulas against persisted Kite/NSE bars without publishing."""

from datetime import date, timedelta

from run import create_app
from src.application.research_strategy2 import strategy2_factors, strategy2_indicators


def main() -> int:
    services = create_app().extensions["screener_services"]
    target = date(2026, 9, 11)
    histories = services.market.histories(target - timedelta(days=420), target)
    benchmark_id = str(services.market.instrument("NIFTY 500")["instrument_id"])
    benchmark = histories[benchmark_id][0]
    values = {}
    for symbol in ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"):
        instrument_id = str(services.market.instrument(symbol)["instrument_id"])
        inputs = strategy2_indicators(histories[instrument_id][0], benchmark)
        if inputs is None:
            raise RuntimeError(f"Strategy 2 inputs are unavailable for {symbol}")
        values[symbol] = inputs
    factors = strategy2_factors(values)
    if len(factors) != 5:
        raise RuntimeError("Strategy 2 factor calculation is incomplete")
    for symbol, output in factors.items():
        if not all(0 <= factor <= 100 for factor in output.values()):
            raise RuntimeError(f"Strategy 2 factors out of range for {symbol}")
        print(
            f"strategy2_probe={symbol} trend={output['trend']:.3f} "
            f"momentum={output['momentum']:.3f} eligible={values[symbol]['penalty']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
