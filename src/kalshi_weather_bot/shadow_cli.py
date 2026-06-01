from __future__ import annotations

import argparse

from dotenv import load_dotenv

from .config import Settings
from .fees import FeeModel
from .shadow import PRODUCTION_BASE_URL, ProductionShadowTracker
from .storage import Store


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Phase 2.75 production-market shadow tracker; never submits orders")
    parser.add_argument("--limit", type=int, default=None, help="Max production markets to fetch per configured series")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--production-base-url", default=None, help=f"Production read base URL (default: env KALSHI_SHADOW_BASE_URL or {PRODUCTION_BASE_URL})")
    parser.add_argument("--settle", action="store_true", help="Also reconcile unsettled shadow fills against production market results")
    args = parser.parse_args(argv)

    settings = Settings()
    store = Store(args.db)
    tracker = ProductionShadowTracker(
        settings,
        store,
        quantity=args.quantity,
        fee_model=FeeModel(rate=args.fee_rate),
        production_base_url=args.production_base_url,
    )
    result = tracker.run_once(args.limit or settings.kalshi_market_limit)
    settled = tracker.reconcile_settlements() if args.settle else None
    summary = store.summary()

    print("mode: production_shadow_no_orders")
    print(f"production_base_url: {tracker.production_base_url}")
    print(f"scan_id: {result.scan_id}")
    print(f"markets_seen: {result.markets_seen}")
    print(f"snapshots_recorded: {result.snapshots_recorded}")
    print(f"shadow_orders_filled: {result.shadow_orders_filled}")
    print(f"skipped_no_liquidity: {result.skipped_no_liquidity}")
    print(f"skipped_no_edge: {result.skipped_no_edge}")
    if settled is not None:
        print(f"shadow_settlement_markets_checked: {settled.markets_checked}")
        print(f"shadow_orders_settled: {settled.orders_settled}")
    print(f"db: {args.db}")
    print(f"total_shadow_snapshots: {summary['shadow_snapshots']}")
    print(f"total_shadow_orders: {summary['shadow_orders']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
