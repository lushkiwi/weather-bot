from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SafetySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    max_orders_per_day: int = Field(default=20, alias="MAX_ORDERS_PER_DAY")
    max_contracts_per_market: int = Field(default=3, alias="MAX_CONTRACTS_PER_MARKET")
    max_contracts_per_event: int = Field(default=1, alias="MAX_CONTRACTS_PER_EVENT")
    max_event_exposure_cents: float = Field(default=1500.0, alias="MAX_EVENT_EXPOSURE_CENTS")
    max_total_exposure_cents: float = Field(default=5000.0, alias="MAX_TOTAL_EXPOSURE_CENTS")
    disallow_multiple_positions_per_event: bool = Field(default=True, alias="DISALLOW_MULTIPLE_POSITIONS_PER_EVENT")
    min_trade_probability: float = Field(default=0.55, alias="MIN_TRADE_PROBABILITY")
    order_cooldown_minutes: int = Field(default=240, alias="ORDER_COOLDOWN_MINUTES")
    disallow_opposite_side_same_market: bool = Field(default=True, alias="DISALLOW_OPPOSITE_SIDE_SAME_MARKET")
    min_yes_ask_cents: float = Field(default=1.0, alias="MIN_YES_ASK_CENTS")
    max_yes_ask_cents: float = Field(default=97.0, alias="MAX_YES_ASK_CENTS")
    min_no_ask_cents: float = Field(default=1.0, alias="MIN_NO_ASK_CENTS")
    max_no_ask_cents: float = Field(default=97.0, alias="MAX_NO_ASK_CENTS")
    min_fee_adjusted_ev_cents: float | None = Field(default=None, alias="MIN_FEE_ADJUSTED_EV_CENTS")


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str | None = None


class SafetyGuard:
    """Hard safety checks for local paper and optional Kalshi demo execution."""

    def __init__(self, settings: SafetySettings | None = None):
        self.settings = settings or SafetySettings()

    def check(
        self,
        *,
        store,
        ticker: str,
        side: str,
        quantity: int,
        ask_cents: float,
        fee_adjusted_ev_cents: float,
        default_min_ev_cents: float,
        event_ticker: str | None = None,
        probability_win: float | None = None,
    ) -> SafetyDecision:
        min_ev = self.settings.min_fee_adjusted_ev_cents
        if min_ev is None:
            min_ev = default_min_ev_cents
        if fee_adjusted_ev_cents < min_ev:
            return SafetyDecision(False, "insufficient_fee_adjusted_edge")
        if probability_win is not None and probability_win < self.settings.min_trade_probability:
            return SafetyDecision(False, "probability_below_min_trade_probability")
        min_price = self.settings.min_no_ask_cents if side == "BUY_NO" else self.settings.min_yes_ask_cents
        max_price = self.settings.max_no_ask_cents if side == "BUY_NO" else self.settings.max_yes_ask_cents
        if ask_cents < min_price:
            return SafetyDecision(False, "ask_below_min_price")
        if ask_cents > max_price:
            return SafetyDecision(False, "ask_above_max_price")
        if store.count_orders_today() >= self.settings.max_orders_per_day:
            return SafetyDecision(False, "max_orders_per_day")
        if self.settings.order_cooldown_minutes > 0 and store.count_orders_since(ticker, side, self.settings.order_cooldown_minutes) > 0:
            return SafetyDecision(False, "cooldown_same_market_side")
        if self.settings.disallow_opposite_side_same_market and store.has_opposite_position(ticker, side):
            return SafetyDecision(False, "opposite_side_position")
        if store.position_quantity(ticker, side) + quantity > self.settings.max_contracts_per_market:
            return SafetyDecision(False, "max_contracts_per_market")
        # Event-level caps treat one city/day's correlated ladder as a single risk, not N markets.
        if event_ticker is not None:
            if self.settings.disallow_multiple_positions_per_event and store.event_order_quantity(event_ticker) > 0:
                return SafetyDecision(False, "event_already_traded")
            if store.event_position_quantity(event_ticker) + quantity > self.settings.max_contracts_per_event:
                return SafetyDecision(False, "max_contracts_per_event")
            if store.event_open_exposure_cents(event_ticker) + (quantity * ask_cents) > self.settings.max_event_exposure_cents:
                return SafetyDecision(False, "max_event_exposure")
        projected_exposure = store.total_open_exposure_cents() + (quantity * ask_cents)
        if projected_exposure > self.settings.max_total_exposure_cents:
            return SafetyDecision(False, "max_total_exposure")
        return SafetyDecision(True)
