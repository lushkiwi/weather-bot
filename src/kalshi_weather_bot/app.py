from __future__ import annotations

import argparse
import threading
import time
from datetime import datetime
from http.server import ThreadingHTTPServer

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
from .web_ui import DEFAULT_DB, DashboardHandler


def runner_loop(
    *,
    settings: Settings,
    db_path: str,
    limit: int,
    interval_seconds: int,
    quantity: int,
    fee_rate: float,
    execute_demo: bool,
    production_shadow: bool,
    stop_event: threading.Event,
) -> None:
    store = Store(db_path)
    safety = SafetyGuard()
    client = KalshiClient(settings)
    demo_executor = DemoExecutor(client, store) if execute_demo else None
    store.insert_runner_event("info", f"app_runner_start execute_demo={execute_demo} production_shadow={production_shadow} interval={interval_seconds}")

    while not stop_event.is_set():
        started = datetime.now().isoformat(timespec="seconds")
        try:
            trader = PaperTrader(
                settings,
                store,
                quantity=quantity,
                fee_model=FeeModel(rate=fee_rate),
                demo_executor=demo_executor,
                safety_guard=safety,
            )
            result = trader.run_once(limit)
            pnl = reconcile_paper_settlements(settings, store)
            shadow_msg = ""
            if production_shadow:
                shadow = ProductionShadowTracker(settings, store, quantity=quantity, fee_model=FeeModel(rate=fee_rate))
                shadow_result = shadow.run_once(limit)
                shadow_pnl = shadow.reconcile_settlements()
                shadow_msg = (
                    f" shadow_scan_id={shadow_result.scan_id} shadow_markets={shadow_result.markets_seen} "
                    f"shadow_snapshots={shadow_result.snapshots_recorded} shadow_fills={shadow_result.shadow_orders_filled} "
                    f"shadow_market_errors={shadow_result.market_errors} "
                    f"shadow_pnl_checked={shadow_pnl.markets_checked} shadow_pnl_settled={shadow_pnl.orders_settled}"
                )
            msg = (
                f"scan_id={result.scan_id} markets={result.markets_seen} signals={result.signals_recorded} "
                f"local_fills={result.orders_filled} demo_submitted={result.demo_orders_submitted} "
                f"demo_errors={result.demo_order_errors} no_liq={result.skipped_no_liquidity} no_edge={result.skipped_no_edge} "
                f"pnl_checked={pnl.markets_checked} pnl_settled={pnl.orders_settled}{shadow_msg}"
            )
            store.insert_runner_event("info", msg)
            _safe_print(f"[{started}] {msg}")
        except Exception as exc:  # noqa: BLE001
            msg = f"app_runner_error {type(exc).__name__}: {exc}"
            store.insert_runner_event("error", msg)
            _safe_print(f"[{started}] {msg}")

        stop_event.wait(max(interval_seconds, 30))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Run the Kalshi weather dashboard plus automatic scanner/demo trader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=None, help="Max markets to fetch per configured series")
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--execute-demo", action="store_true", help="Submit qualifying FOK orders to Kalshi demo")
    parser.add_argument("--production-shadow", action="store_true", help="Also run production-market shadow tracking without submitting orders")
    args = parser.parse_args(argv)

    settings = Settings()
    # Hosted Postgres (DATABASE_URL) takes precedence over the local SQLite path.
    db_target = settings.database_url or args.db
    client = KalshiClient(settings)
    if args.execute_demo and not client.is_demo:
        raise RuntimeError("Refusing automatic execution because KALSHI_BASE_URL is not a demo URL.")

    Store(db_target).insert_runner_event("info", f"app_start execute_demo={args.execute_demo} dashboard=http://{args.host}:{args.port}")
    stop_event = threading.Event()
    thread = threading.Thread(
        target=runner_loop,
        kwargs={
            "settings": settings,
            "db_path": db_target,
            "limit": args.limit or settings.kalshi_market_limit,
            "interval_seconds": args.interval_seconds,
            "quantity": args.quantity,
            "fee_rate": args.fee_rate,
            "execute_demo": args.execute_demo,
            "production_shadow": args.production_shadow,
            "stop_event": stop_event,
        },
        name="kalshi-weather-runner",
        daemon=True,
    )
    thread.start()

    DashboardHandler.db_path = db_target
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    _safe_print(f"Dashboard running at http://{args.host}:{args.port}")
    _safe_print(f"Automatic scanner interval: {args.interval_seconds}s")
    _safe_print(f"Demo execution: {args.execute_demo}")
    _safe_print(f"Production shadow: {args.production_shadow}")
    _safe_print(f"Using database: {'postgres' if settings.database_url else args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _safe_print("Stopping...")
    finally:
        stop_event.set()
        server.server_close()
    return 0


def _safe_print(message: str) -> None:
    try:
        print(message, flush=True)
    except OSError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
