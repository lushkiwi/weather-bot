from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from .config import Settings
from .kalshi_client import KalshiClient
from .market_parser import parse_market
from .models import EdgeSignal, WeatherVariable
from .orderbook import parse_market_quote, parse_orderbook
from .probability import estimate_probability
from .weather import OpenMeteoClient, value_for_variable


class WeatherMarketScanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.kalshi = KalshiClient(settings)
        self.weather = OpenMeteoClient(settings)
        self._geo_cache: dict[str, tuple[float, float, str] | None] = {}
        self._hourly_cache: dict[tuple[float, float, object, int], float | None] = {}
        self._daily_cache: dict[tuple[float, float, object], dict | None] = {}

    def scan(self, limit: int | None = None) -> list[EdgeSignal]:
        signals: list[EdgeSignal] = []
        market_limit = limit or self.settings.kalshi_market_limit
        series_tickers = self.settings.series_ticker_list()
        market_iter = (
            market
            for series_ticker in series_tickers
            for market in self.kalshi.iter_markets(limit=market_limit, series_ticker=series_ticker)
        ) if series_tickers else self.kalshi.iter_markets(limit=market_limit)
        for market in market_iter:
            if not _market_is_tradeable(market):
                continue
            parsed = parse_market(market)
            if not parsed or not _usable(parsed):
                continue

            geo = self._geocode(parsed.city or "")
            if not geo:
                continue
            lat, lon, resolved_city = geo
            if parsed.variable == WeatherVariable.POINT_TEMP_F and parsed.target_hour is not None:
                forecast_value = self._hourly_temperature(
                    lat,
                    lon,
                    parsed.target_date,  # type: ignore[arg-type]
                    parsed.target_hour,
                )
            else:
                daily = self._daily_forecast(lat, lon, parsed.target_date)  # type: ignore[arg-type]
                if not daily:
                    continue
                forecast_value = value_for_variable(daily, parsed.variable)
            if forecast_value is None:
                continue

            quote = parse_orderbook(self.kalshi.get_orderbook(parsed.ticker))
            used_orderbook = quote.yes_ask is not None
            if not used_orderbook:
                quote = parse_market_quote(market)
                ask_size = _float_or_zero(market.get("yes_ask_size_fp"))
                if ask_size <= 0:
                    continue
            # For a buy-YES edge, compare our fair value to the executable YES ask.
            # Mid/bid prices are not executable and can create false positives.
            market_yes = quote.yes_ask
            if market_yes is None or market_yes <= 0:
                continue

            estimate = estimate_probability(
                mean=forecast_value,
                threshold=parsed.threshold,  # type: ignore[arg-type]
                variable=parsed.variable,
                target_date=parsed.target_date,  # type: ignore[arg-type]
                comparator=parsed.comparator,
            )
            fair_yes = estimate.probability_yes * 100.0
            edge = fair_yes - market_yes
            if edge >= self.settings.min_edge_cents:
                signals.append(
                    EdgeSignal(
                        ticker=parsed.ticker,
                        title=parsed.title,
                        city=resolved_city,
                        variable=parsed.variable,
                        target_date=parsed.target_date,  # type: ignore[arg-type]
                        threshold=parsed.threshold,  # type: ignore[arg-type]
                        probability_yes=estimate.probability_yes,
                        fair_yes_cents=fair_yes,
                        market_yes_cents=market_yes,
                        edge_cents=edge,
                        quote=quote,
                        notes=parsed.notes
                        + (f"forecast_mean={forecast_value:.2f}", f"forecast_sigma={estimate.sigma:.2f}", f"target_hour={parsed.target_hour}"),
                    )
                )
        return sorted(signals, key=lambda s: s.edge_cents, reverse=True)


    def _geocode(self, city: str) -> tuple[float, float, str] | None:
        if city not in self._geo_cache:
            self._geo_cache[city] = self.weather.geocode(city)
        return self._geo_cache[city]

    def _hourly_temperature(self, lat: float, lon: float, target_date, target_hour: int) -> float | None:
        key = (lat, lon, target_date, target_hour)
        if key not in self._hourly_cache:
            self._hourly_cache[key] = self.weather.hourly_temperature(lat, lon, target_date, target_hour)
        return self._hourly_cache[key]

    def _daily_forecast(self, lat: float, lon: float, target_date) -> dict | None:
        key = (lat, lon, target_date)
        if key not in self._daily_cache:
            self._daily_cache[key] = self.weather.daily_forecast(lat, lon, target_date)
        return self._daily_cache[key]


def _market_is_tradeable(market: dict) -> bool:
    status = str(market.get("status") or "").lower()
    if status and status not in {"active", "open"}:
        return False
    close_time = market.get("close_time")
    if close_time:
        try:
            close_dt = datetime.fromisoformat(str(close_time).replace("Z", "+00:00"))
            if close_dt <= datetime.now(timezone.utc):
                return False
        except ValueError:
            pass
    return True


def _float_or_zero(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _usable(parsed) -> bool:
    return bool(
        parsed.city
        and parsed.target_date
        and parsed.threshold is not None
        and parsed.variable != WeatherVariable.UNKNOWN
        and (parsed.variable != WeatherVariable.POINT_TEMP_F or parsed.target_hour is not None)
    )


def signal_to_dict(signal: EdgeSignal) -> dict:
    data = asdict(signal)
    data["variable"] = signal.variable.value
    data["target_date"] = signal.target_date.isoformat()
    return data
