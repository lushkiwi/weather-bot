from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FeeModel:
    """Approximate Kalshi fee model for Phase 2 paper trading.

    Kalshi fees should be verified against the active fee schedule before live trading.
    This model is intentionally configurable and conservative for research.
    """

    rate: float = 0.07
    round_up: bool = True

    def buy_fee_cents(self, price_cents: float, quantity: int = 1) -> float:
        price = min(max(price_cents / 100.0, 0.0), 1.0)
        raw_cents = self.rate * price * (1.0 - price) * 100.0 * quantity
        return float(math.ceil(raw_cents)) if self.round_up and raw_cents > 0 else raw_cents

    def buy_ev_cents(self, probability_win: float, price_cents: float, quantity: int = 1) -> float:
        gross = ((probability_win * 100.0) - price_cents) * quantity
        return gross - self.buy_fee_cents(price_cents, quantity)

    def buy_yes_fee_cents(self, price_cents: float, quantity: int = 1) -> float:
        return self.buy_fee_cents(price_cents, quantity)

    def buy_yes_ev_cents(self, probability_yes: float, price_cents: float, quantity: int = 1) -> float:
        return self.buy_ev_cents(probability_yes, price_cents, quantity)

    def buy_no_fee_cents(self, price_cents: float, quantity: int = 1) -> float:
        return self.buy_fee_cents(price_cents, quantity)

    def buy_no_ev_cents(self, probability_yes: float, price_cents: float, quantity: int = 1) -> float:
        return self.buy_ev_cents(1.0 - probability_yes, price_cents, quantity)
