from __future__ import annotations

import uuid
from dataclasses import dataclass

from .kalshi_client import KalshiClient
from .storage import Store


@dataclass(frozen=True)
class DemoOrderResult:
    client_order_id: str
    status: str
    kalshi_order_id: str | None
    response: dict | None
    error: str | None = None


class DemoExecutor:
    """Places orders only against a Kalshi demo API base URL."""

    def __init__(self, client: KalshiClient, store: Store):
        if not client.is_demo:
            raise RuntimeError(
                "Demo execution refused because KALSHI_BASE_URL is not a demo URL. "
                "Use https://demo-api.kalshi.co/trade-api/v2 for demo orders."
            )
        self.client = client
        self.store = store

    def buy_yes_fok(
        self,
        *,
        scan_id: int,
        signal_id: int,
        local_order_id: int | None,
        ticker: str,
        quantity: int,
        price_cents: float,
    ) -> DemoOrderResult:
        client_order_id = f"kwb-{scan_id}-{signal_id}-{uuid.uuid4().hex[:12]}"
        price_dollars = f"{price_cents / 100.0:.4f}"
        count = f"{quantity:.2f}"
        try:
            response = self.client.create_event_order(
                ticker=ticker,
                client_order_id=client_order_id,
                side="bid",
                count=count,
                price=price_dollars,
                time_in_force="fill_or_kill",
            )
            order = response.get("order") if isinstance(response, dict) else None
            kalshi_order_id = None
            status = "SUBMITTED"
            if isinstance(order, dict):
                kalshi_order_id = order.get("order_id")
                status = str(order.get("status") or status).upper()
            self.store.insert_demo_order(scan_id, signal_id, {
                "local_order_id": local_order_id,
                "ticker": ticker,
                "client_order_id": client_order_id,
                "kalshi_order_id": kalshi_order_id,
                "side": "BUY_YES",
                "quantity": count,
                "price_dollars": price_dollars,
                "status": status,
                "response_json": response,
                "error": None,
            })
            return DemoOrderResult(client_order_id, status, kalshi_order_id, response)
        except Exception as exc:  # noqa: BLE001
            self.store.insert_demo_order(scan_id, signal_id, {
                "local_order_id": local_order_id,
                "ticker": ticker,
                "client_order_id": client_order_id,
                "kalshi_order_id": None,
                "side": "BUY_YES",
                "quantity": count,
                "price_dollars": price_dollars,
                "status": "ERROR",
                "response_json": None,
                "error": str(exc),
            })
            return DemoOrderResult(client_order_id, "ERROR", None, None, str(exc))

    def buy_no_fok(
        self,
        *,
        scan_id: int,
        signal_id: int,
        local_order_id: int | None,
        ticker: str,
        quantity: int,
        price_cents: float,
    ) -> DemoOrderResult:
        """Buy NO in demo by placing an ASK on the YES book at 100 - NO price.

        Kalshi binary markets are a single YES book: buying NO at N cents is
        equivalent to selling/asking YES at 100-N cents. This stays demo-only
        and fill-or-kill, matching the local paper fill assumption.
        """
        client_order_id = f"kwb-{scan_id}-{signal_id}-{uuid.uuid4().hex[:12]}"
        no_price_dollars = f"{price_cents / 100.0:.4f}"
        yes_book_price_dollars = f"{(100.0 - price_cents) / 100.0:.4f}"
        count = f"{quantity:.2f}"
        try:
            response = self.client.create_event_order(
                ticker=ticker,
                client_order_id=client_order_id,
                side="ask",
                count=count,
                price=yes_book_price_dollars,
                time_in_force="fill_or_kill",
            )
            order = response.get("order") if isinstance(response, dict) else None
            kalshi_order_id = None
            status = "SUBMITTED"
            if isinstance(order, dict):
                kalshi_order_id = order.get("order_id")
                status = str(order.get("status") or status).upper()
            self.store.insert_demo_order(scan_id, signal_id, {
                "local_order_id": local_order_id,
                "ticker": ticker,
                "client_order_id": client_order_id,
                "kalshi_order_id": kalshi_order_id,
                "side": "BUY_NO",
                "quantity": count,
                "price_dollars": no_price_dollars,
                "status": status,
                "response_json": response,
                "error": None,
            })
            return DemoOrderResult(client_order_id, status, kalshi_order_id, response)
        except Exception as exc:  # noqa: BLE001
            self.store.insert_demo_order(scan_id, signal_id, {
                "local_order_id": local_order_id,
                "ticker": ticker,
                "client_order_id": client_order_id,
                "kalshi_order_id": None,
                "side": "BUY_NO",
                "quantity": count,
                "price_dollars": no_price_dollars,
                "status": "ERROR",
                "response_json": None,
                "error": str(exc),
            })
            return DemoOrderResult(client_order_id, "ERROR", None, None, str(exc))

    def snapshot_portfolio(self) -> int:
        balance = self.client.get_balance()
        positions = self.client.get_positions(limit=100)
        return self.store.insert_demo_snapshot(balance, positions)
