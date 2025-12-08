import argparse
from services.screener_service import ScreenerService

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Screener V3")
    parser.add_argument("--day0", action="store_true", help="Initialize instruments database from Kite")
    args = parser.parse_args()

    screener = ScreenerService()
    screener.logger.info(f"Starting Stock Screener (Day0 mode: {args.day0})")
    screener.run(day0=args.day0)
