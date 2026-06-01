from __future__ import annotations

import argparse

from dotenv import load_dotenv

from .config import Settings
from .fees import FeeModel
from .paper import PaperTrader
from .storage import Store


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Phase 2 local paper trader for Kalshi weather markets")
    parser.add_argument("--limit", type=int, default=None, help="Max markets to fetch per configured series")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    args = parser.parse_args(argv)

    settings = Settings()
    store = Store(args.db)
    trader = PaperTrader(settings, store, quantity=args.quantity, fee_model=FeeModel(rate=args.fee_rate))
    result = trader.run_once(args.limit or settings.kalshi_market_limit)
    summary = store.summary()

    print(f"scan_id: {result.scan_id}")
    print(f"markets_seen: {result.markets_seen}")
    print(f"signals_recorded: {result.signals_recorded}")
    print(f"orders_filled: {result.orders_filled}")
    print(f"demo_orders_submitted: {result.demo_orders_submitted}")
    print(f"demo_order_errors: {result.demo_order_errors}")
    print(f"skipped_no_liquidity: {result.skipped_no_liquidity}")
    print(f"skipped_no_edge: {result.skipped_no_edge}")
    print(f"db: {args.db}")
    print(f"total_signals: {summary['signals']}")
    print(f"total_orders: {summary['orders']}")
    print(f"open_positions: {summary['positions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
