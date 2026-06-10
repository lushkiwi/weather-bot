from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class WeatherVariable(str, Enum):
    POINT_TEMP_F = "point_temp_f"
    HIGH_TEMP_F = "high_temp_f"
    LOW_TEMP_F = "low_temp_f"
    RAIN_IN = "rain_in"
    SNOW_IN = "snow_in"
    UNKNOWN = "unknown"


# Variables whose markets resolve on a temperature reading; used by the uncertainty gate,
# ensemble sigma, and the NWS forecast blend.
TEMP_VARIABLES = {WeatherVariable.POINT_TEMP_F, WeatherVariable.HIGH_TEMP_F, WeatherVariable.LOW_TEMP_F}


@dataclass(frozen=True)
class ParsedWeatherMarket:
    ticker: str
    title: str
    city: str | None
    target_date: date | None
    target_hour: int | None
    variable: WeatherVariable
    threshold: float | None
    comparator: str | None
    confidence: float
    band_lower: float | None = None
    band_upper: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderbookQuote:
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None

    @property
    def mid_yes(self) -> float | None:
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2
        if self.yes_ask is not None:
            return self.yes_ask
        if self.yes_bid is not None:
            return self.yes_bid
        return None


@dataclass(frozen=True)
class ForecastEstimate:
    mean: float
    sigma: float
    probability_yes: float
    source: str


@dataclass(frozen=True)
class EdgeSignal:
    ticker: str
    title: str
    city: str
    variable: WeatherVariable
    target_date: date
    threshold: float
    probability_yes: float
    fair_yes_cents: float
    market_yes_cents: float
    edge_cents: float
    quote: OrderbookQuote
    notes: tuple[str, ...]
