from __future__ import annotations

from typing import Any

from .models import OrderbookQuote


def parse_market_quote(market: dict[str, Any]) -> OrderbookQuote:
    return OrderbookQuote(
        yes_bid=_dollars_to_cents(market.get("yes_bid_dollars")),
        yes_ask=_dollars_to_cents(market.get("yes_ask_dollars")),
        no_bid=_dollars_to_cents(market.get("no_bid_dollars")),
        no_ask=_dollars_to_cents(market.get("no_ask_dollars")),
    )


def parse_orderbook(payload: dict[str, Any]) -> OrderbookQuote:
    book = payload.get("orderbook") or payload.get("results") or payload
    yes = book.get("yes") or []
    no = book.get("no") or []
    yes_bid = _best_bid(yes)
    yes_ask = _best_ask_from_no(no)
    no_bid = _best_bid(no)
    no_ask = _best_ask_from_no(yes)
    return OrderbookQuote(yes_bid=yes_bid, yes_ask=yes_ask, no_bid=no_bid, no_ask=no_ask)


def _dollars_to_cents(value: Any) -> float | None:
    try:
        return float(value) * 100.0
    except (TypeError, ValueError):
        return None


def _price(level: Any) -> float | None:
    if isinstance(level, dict):
        raw = level.get("price") or level.get("yes_price") or level.get("no_price")
    elif isinstance(level, (list, tuple)) and level:
        raw = level[0]
    else:
        raw = None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _best_bid(levels: list[Any]) -> float | None:
    prices = [p for p in (_price(level) for level in levels) if p is not None]
    return max(prices) if prices else None


def _best_ask_from_no(opposite_levels: list[Any]) -> float | None:
    # Buying YES is equivalent to selling NO; yes ask is 100 - best no bid.
    best_opposite_bid = _best_bid(opposite_levels)
    return 100.0 - best_opposite_bid if best_opposite_bid is not None else None
