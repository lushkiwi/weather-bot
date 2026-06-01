from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .kalshi_client import KalshiClient
from .storage import Store


@dataclass(frozen=True)
class ReconcileResult:
    markets_checked: int
    orders_settled: int
    errors: int


def reconcile_paper_settlements(settings: Settings, store: Store, limit: int | None = None) -> ReconcileResult:
    client = KalshiClient(settings)
    tickers = store.unsettled_order_tickers()
    if limit is not None:
        tickers = tickers[:limit]
    checked = settled = errors = 0
    for ticker in tickers:
        try:
            market = client.get_market(ticker)
            checked += 1
            settled += store.settle_paper_orders_for_market(ticker, market)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            store.insert_runner_event("error", f"pnl_reconcile_error ticker={ticker} {type(exc).__name__}: {exc}")
    store.insert_runner_event("info", f"pnl_reconcile markets_checked={checked} orders_settled={settled} errors={errors}")
    return ReconcileResult(checked, settled, errors)
