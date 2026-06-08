from __future__ import annotations

import argparse
import time
from datetime import datetime

from dotenv import load_dotenv

from .config import Settings
from .demo_execution import DemoExecutor
from .fees import FeeModel
from .kalshi_client import KalshiClient
from .paper import PaperTrader
from .pnl import reconcile_paper_settlements
from .safety import SafetyGuard
from .shadow import ProductionShadowTracker
from .storage import Store


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Continuous Kalshi weather bot runner")
    parser.add_argument("--limit", type=int, default=None, help="Max markets to fetch per configured series")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--execute-demo", action="store_true", help="Submit qualifying FOK orders to Kalshi demo")
    parser.add_argument("--production-shadow", action="store_true", help="Also run production-market shadow tracking without submitting orders")
    parser.add_argument(
        "--shadow-only",
        action="store_true",
        help="Skip the demo-API paper scan and demo execution; run only the read-only production shadow scan + settlement (needs only production read credentials)",
    )
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit")
    args = parser.parse_args(argv)

    settings = Settings()
    # Hosted Postgres (DATABASE_URL) takes precedence over the local SQLite path.
    db_target = settings.database_url or args.db
    store = Store(db_target)
    safety = SafetyGuard()

    shadow_only = args.shadow_only
    # --shadow-only implies running the production shadow scan.
    production_shadow = args.production_shadow or shadow_only

    # The primary (demo-API) client/executor are only needed for the paper/demo path; building
    # KalshiClient eagerly loads the demo private key, which a shadow-only cloud run does not have.
    client = None
    demo_executor = None
    if not shadow_only:
        client = KalshiClient(settings)
        demo_executor = DemoExecutor(client, store) if args.execute_demo else None

    store.insert_runner_event(
        "info",
        f"runner_start shadow_only={shadow_only} execute_demo={bool(demo_executor)} "
        f"production_shadow={production_shadow} interval={args.interval_seconds}",
    )
    print(f"Runner started at {datetime.now().isoformat(timespec='seconds')}")
    print(f"DB: {'postgres' if settings.database_url else args.db}")
    print(f"Interval seconds: {args.interval_seconds}")
    print(f"Shadow only: {shadow_only}")
    print(f"Demo execution: {bool(demo_executor)}")
    print(f"Production shadow: {production_shadow}")

    while True:
        started = datetime.now().isoformat(timespec="seconds")
        try:
            if shadow_only:
                shadow = ProductionShadowTracker(settings, store, quantity=args.quantity, fee_model=FeeModel(rate=args.fee_rate))
                shadow_result = shadow.run_once(args.limit or settings.kalshi_market_limit)
                shadow_pnl = shadow.reconcile_settlements()
                stale_shadow = store.stale_shadow_orders(settings.stale_unsettled_grace_hours, limit=5)
                if stale_shadow:
                    store.insert_runner_event("warning", f"stale_shadow_orders count={len(stale_shadow)} oldest_id={stale_shadow[0].get('id')}")
                msg = (
                    f"shadow_only scan_id={shadow_result.scan_id} shadow_markets={shadow_result.markets_seen} "
                    f"shadow_snapshots={shadow_result.snapshots_recorded} shadow_fills={shadow_result.shadow_orders_filled} "
                    f"shadow_no_liq={shadow_result.skipped_no_liquidity} shadow_no_edge={shadow_result.skipped_no_edge} "
                    f"shadow_market_errors={shadow_result.market_errors} "
                    f"shadow_pnl_checked={shadow_pnl.markets_checked} shadow_pnl_settled={shadow_pnl.orders_settled} "
                    f"stale_shadow_orders={len(stale_shadow)}"
                )
            else:
                trader = PaperTrader(
                    settings,
                    store,
                    quantity=args.quantity,
                    fee_model=FeeModel(rate=args.fee_rate),
                    demo_executor=demo_executor,
                    safety_guard=safety,
                )
                result = trader.run_once(args.limit or settings.kalshi_market_limit)
                pnl = reconcile_paper_settlements(settings, store)
                shadow_msg = ""
                if production_shadow:
                    shadow = ProductionShadowTracker(settings, store, quantity=args.quantity, fee_model=FeeModel(rate=args.fee_rate))
                    shadow_result = shadow.run_once(args.limit or settings.kalshi_market_limit)
                    shadow_pnl = shadow.reconcile_settlements()
                    stale_shadow = store.stale_shadow_orders(settings.stale_unsettled_grace_hours, limit=5)
                    if stale_shadow:
                        store.insert_runner_event("warning", f"stale_shadow_orders count={len(stale_shadow)} oldest_id={stale_shadow[0].get('id')}")
                    shadow_msg = (
                        f" shadow_scan_id={shadow_result.scan_id} shadow_markets={shadow_result.markets_seen} "
                        f"shadow_snapshots={shadow_result.snapshots_recorded} shadow_fills={shadow_result.shadow_orders_filled} "
                        f"shadow_no_liq={shadow_result.skipped_no_liquidity} shadow_no_edge={shadow_result.skipped_no_edge} "
                        f"shadow_market_errors={shadow_result.market_errors} "
                        f"shadow_pnl_checked={shadow_pnl.markets_checked} shadow_pnl_settled={shadow_pnl.orders_settled} "
                        f"stale_shadow_orders={len(stale_shadow)}"
                    )
                msg = (
                    f"scan_id={result.scan_id} markets={result.markets_seen} signals={result.signals_recorded} "
                    f"local_fills={result.orders_filled} demo_submitted={result.demo_orders_submitted} "
                    f"demo_errors={result.demo_order_errors} no_liq={result.skipped_no_liquidity} no_edge={result.skipped_no_edge} "
                    f"market_errors={result.market_errors} "
                    f"pnl_checked={pnl.markets_checked} pnl_settled={pnl.orders_settled}{shadow_msg}"
                )
            store.insert_runner_event("info", msg)
            print(f"[{started}] {msg}", flush=True)
        except Exception as exc:  # noqa: BLE001
            msg = f"runner_error {type(exc).__name__}: {exc}"
            store.insert_runner_event("error", msg)
            print(f"[{started}] {msg}", flush=True)

        if args.once:
            break
        time.sleep(max(args.interval_seconds, 30))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
