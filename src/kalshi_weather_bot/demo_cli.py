from __future__ import annotations

import argparse

from dotenv import load_dotenv

from .config import Settings
from .demo_execution import DemoExecutor
from .fees import FeeModel
from .kalshi_client import KalshiClient
from .paper import PaperTrader
from .storage import Store


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Phase 2.5 Kalshi demo execution backend")
    parser.add_argument("--limit", type=int, default=None, help="Max markets to fetch per configured series")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--snapshot", action="store_true", help="Fetch demo balance/positions and store a snapshot")
    parser.add_argument("--execute-demo", action="store_true", help="Actually submit qualifying FOK orders to Kalshi demo")
    args = parser.parse_args(argv)

    settings = Settings()
    store = Store(settings.database_url or args.db)
    client = KalshiClient(settings)
    executor = DemoExecutor(client, store)

    if args.snapshot:
        snapshot_id = executor.snapshot_portfolio()
        balance = client.get_balance()
        positions = client.get_positions(limit=100)
        market_positions = positions.get("market_positions") or positions.get("positions") or []
        event_positions = positions.get("event_positions") or []
        print(f"snapshot_id: {snapshot_id}")
        print(f"demo_balance_cents: {balance.get('balance')}")
        print(f"demo_portfolio_value_cents: {balance.get('portfolio_value')}")
        print(f"demo_market_positions_count: {len(market_positions)}")
        print(f"demo_event_positions_count: {len(event_positions)}")

    if not args.execute_demo:
        print("Demo execution not enabled. Add --execute-demo to submit qualifying demo FOK orders.")
        print("Safety: this command refuses non-demo Kalshi base URLs.")
        return 0

    trader = PaperTrader(
        settings,
        store,
        quantity=args.quantity,
        fee_model=FeeModel(rate=args.fee_rate),
        demo_executor=executor,
    )
    result = trader.run_once(args.limit or settings.kalshi_market_limit)
    summary = store.summary()
    print(f"scan_id: {result.scan_id}")
    print(f"markets_seen: {result.markets_seen}")
    print(f"signals_recorded: {result.signals_recorded}")
    print(f"local_orders_filled: {result.orders_filled}")
    print(f"demo_orders_submitted: {result.demo_orders_submitted}")
    print(f"demo_order_errors: {result.demo_order_errors}")
    print(f"skipped_no_liquidity: {result.skipped_no_liquidity}")
    print(f"skipped_no_edge: {result.skipped_no_edge}")
    print(f"total_demo_orders: {summary['demo_orders']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
