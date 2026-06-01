from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .config import Settings


class KalshiClient:
    """Minimal Kalshi API client for market data and optional demo execution."""

    def __init__(self, settings: Settings):
        settings.require_kalshi_auth()
        self.base_url = settings.kalshi_base_url.rstrip("/")
        self.key_id = settings.kalshi_api_key_id or ""
        self.private_key = self._load_private_key(settings)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})

    def _load_private_key(self, settings: Settings):
        # Prefer a key file when supplied. It is less error-prone than putting
        # multiline PEM material directly in .env.
        if settings.kalshi_private_key_path:
            pem = Path(settings.kalshi_private_key_path).read_bytes()
        else:
            key_text = settings.kalshi_private_key or ""
            # Allow single-line .env values with escaped newlines.
            pem = key_text.replace("\\n", "\n").encode("utf-8")
        try:
            return serialization.load_pem_private_key(pem, password=None)
        except ValueError as exc:
            raise RuntimeError(
                "Could not load Kalshi private key. Prefer KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem, "
                "or set KALSHI_PRIVATE_KEY as one quoted line with escaped \\n characters."
            ) from exc

    def _headers(self, method: str, path_with_query: str) -> dict[str, str]:
        # Kalshi signs timestamp + method + path. Path includes /trade-api/v2/... and query string if present.
        ts_ms = str(int(time.time() * 1000))
        msg = f"{ts_ms}{method.upper()}{path_with_query}".encode("utf-8")
        sig = self.private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("ascii"),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        qs = f"?{urlencode(params, doseq=True)}" if params else ""
        clean_path = path if path.startswith("/") else f"/{path}"
        api_prefix = urlparse(self.base_url).path.rstrip("/") or "/trade-api/v2"
        path_with_query = f"{api_prefix}{clean_path}{qs}" if not clean_path.startswith(api_prefix) else f"{clean_path}{qs}"
        url = f"{self.base_url}{clean_path}{qs}"
        headers = self._headers(method, path_with_query)
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(4):
            resp = self.session.request(
                method,
                url,
                headers=headers,
                data=json.dumps(body) if body is not None else None,
                timeout=30,
            )
            if resp.status_code != 429 or attempt == 3:
                break
            retry_after = resp.headers.get("Retry-After")
            try:
                sleep_seconds = float(retry_after) if retry_after else 2 ** attempt
            except ValueError:
                sleep_seconds = 2 ** attempt
            time.sleep(max(sleep_seconds, 1.0))
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            detail = resp.text[:1000] if resp.text else ""
            raise requests.HTTPError(f"{exc}; response_body={detail}", response=resp) from exc
        return resp.json() if resp.content else {}

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body=body)

    @property
    def is_demo(self) -> bool:
        return "demo" in self.base_url.lower()

    def iter_markets(self, limit: int = 50, status: str = "open", series_ticker: str | None = None):
        remaining = limit
        cursor: str | None = None
        while remaining > 0:
            page_size = min(remaining, 1000)
            payload = self.get(
                "/markets",
                {"status": status, "limit": page_size, "cursor": cursor, "series_ticker": series_ticker},
            )
            markets = payload.get("markets") or payload.get("results") or []
            if not markets:
                return
            for market in markets:
                yield market
                remaining -= 1
                if remaining <= 0:
                    return
            cursor = payload.get("cursor")
            if not cursor:
                return

    def get_market(self, ticker: str) -> dict[str, Any]:
        payload = self.get(f"/markets/{ticker}")
        return payload.get("market") or payload

    def get_orderbook(self, ticker: str) -> dict[str, Any]:
        return self.get(f"/markets/{ticker}/orderbook")

    def get_balance(self) -> dict[str, Any]:
        return self.get("/portfolio/balance")

    def get_positions(self, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        # Demo shared API currently accepts the endpoint reliably without query
        # params; some query combinations return 401 despite valid auth.
        if self.is_demo:
            return self.get("/portfolio/positions")
        return self.get("/portfolio/positions", {"limit": limit, "cursor": cursor})

    def create_event_order(
        self,
        *,
        ticker: str,
        client_order_id: str,
        side: str,
        count: str,
        price: str,
        time_in_force: str = "fill_or_kill",
    ) -> dict[str, Any]:
        return self.post(
            "/portfolio/events/orders",
            {
                "ticker": ticker,
                "client_order_id": client_order_id,
                "side": side,
                "count": count,
                "price": price,
                "time_in_force": time_in_force,
                "self_trade_prevention_type": "taker_at_cross",
            },
        )
