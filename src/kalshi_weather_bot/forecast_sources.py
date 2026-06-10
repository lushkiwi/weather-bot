from __future__ import annotations

"""Shared forecast-input engine for the paper and shadow scan pipelines.

Consolidates the per-run caches and the three forecast inputs that were previously duplicated
(and Open-Meteo-only) in PaperTrader / ProductionShadowTracker:

- ``value``: the point forecast, optionally blended with the NWS point forecast for
  temperature markets (NWS is the settlement source for the daily series, so this directly
  attacks the grid-vs-station basis error that drove past losses);
- ``sigma_base``: the baseline sigma, replaced by the day-specific Open-Meteo ensemble spread
  (plus a station-basis term, in quadrature) when enough members report — the hardcoded
  climatological sigma was simultaneously too tight for hourly temps and too wide for daily
  highs, manufacturing fake tail EV;
- ``rain_probability``: unchanged Open-Meteo precipitation-probability passthrough.

All external fetches are best-effort: any failure falls back to the plain Open-Meteo value or
the static sigma so a provider outage degrades the model instead of failing the scan.
"""

import statistics

from .config import Settings
from .models import TEMP_VARIABLES, WeatherVariable
from .nws import NWSClient
from .probability import base_sigma
from .weather import OpenMeteoClient, value_for_variable


class ForecastEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.open_meteo = OpenMeteoClient(settings)
        self.nws = NWSClient(settings)
        self._geo_cache: dict[str, tuple[float, float, str] | None] = {}
        self._hourly_cache: dict[tuple[float, float, object, int], float | None] = {}
        self._daily_cache: dict[tuple[float, float, object], dict | None] = {}
        self._ensemble_cache: dict[tuple[float, float, object], dict[str, dict[int, float]] | None] = {}

    def geocode(self, city: str) -> tuple[float, float, str] | None:
        if city not in self._geo_cache:
            self._geo_cache[city] = self.open_meteo.geocode(city)
        return self._geo_cache[city]

    def value(self, lat: float, lon: float, parsed) -> tuple[float | None, str | None]:
        """Point forecast for the market's variable, with an optional NWS blend note."""
        open_meteo_value = self._open_meteo_value(lat, lon, parsed)
        if open_meteo_value is None:
            return None, None
        if not self.settings.enable_nws_forecast or parsed.variable not in TEMP_VARIABLES:
            return open_meteo_value, None
        nws_value = self._nws_value(lat, lon, parsed)
        if nws_value is None:
            return open_meteo_value, None
        weight = min(max(self.settings.nws_forecast_weight, 0.0), 1.0)
        blended = weight * nws_value + (1.0 - weight) * open_meteo_value
        return blended, f"nws{int(round(weight * 100))}"

    def sigma_base(self, lat: float, lon: float, parsed) -> tuple[float, str | None]:
        """Baseline sigma: day-specific ensemble spread when available, else the static table.

        Ensemble spread alone understates total error (it carries no grid-vs-station basis), so
        ``ENSEMBLE_BASIS_SIGMA_F`` is added in quadrature and the result is floored at
        ``DYNAMIC_SIGMA_MIN_F``. Dynamic widening from verified realized errors still applies on
        top in apply_forecast_adjustments.
        """
        static = base_sigma(parsed.variable, parsed.target_date)
        if not self.settings.enable_ensemble_sigma or parsed.variable not in TEMP_VARIABLES:
            return static, None
        values = self._ensemble_member_values(lat, lon, parsed)
        if values is None or len(values) < max(self.settings.ensemble_min_members, 2):
            return static, None
        spread = statistics.stdev(values)
        sigma = (
            (spread * self.settings.ensemble_sigma_multiplier) ** 2
            + self.settings.ensemble_basis_sigma_f ** 2
        ) ** 0.5
        sigma = min(max(sigma, self.settings.dynamic_sigma_min_f), self.settings.dynamic_sigma_max_f)
        return sigma, f"ens_sigma{sigma:.1f}_n{len(values)}"

    def rain_probability(self, lat: float, lon: float, parsed) -> float | None:
        """Forecast precipitation probability for an "any rain" market, else None."""
        if parsed.variable != WeatherVariable.RAIN_IN or parsed.threshold is None or parsed.threshold > 0.25:
            return None
        daily = self._daily(lat, lon, parsed.target_date)
        if not daily:
            return None
        try:
            return float(daily.get("precipitation_probability_max")) / 100.0
        except (TypeError, ValueError):
            return None

    def _open_meteo_value(self, lat: float, lon: float, parsed) -> float | None:
        if parsed.variable == WeatherVariable.POINT_TEMP_F and parsed.target_hour is not None:
            key = (lat, lon, parsed.target_date, parsed.target_hour)
            if key not in self._hourly_cache:
                self._hourly_cache[key] = self.open_meteo.hourly_temperature(lat, lon, parsed.target_date, parsed.target_hour)
            return self._hourly_cache[key]
        return value_for_variable(self._daily(lat, lon, parsed.target_date) or {}, parsed.variable)

    def _daily(self, lat: float, lon: float, target_date) -> dict | None:
        key = (lat, lon, target_date)
        if key not in self._daily_cache:
            self._daily_cache[key] = self.open_meteo.daily_forecast(lat, lon, target_date)
        return self._daily_cache[key]

    def _nws_value(self, lat: float, lon: float, parsed) -> float | None:
        try:
            if parsed.variable == WeatherVariable.POINT_TEMP_F and parsed.target_hour is not None:
                return self.nws.hourly_temperature(lat, lon, parsed.target_date, parsed.target_hour)
            if parsed.variable == WeatherVariable.HIGH_TEMP_F:
                return self.nws.daily_high(lat, lon, parsed.target_date)
            if parsed.variable == WeatherVariable.LOW_TEMP_F:
                return self.nws.daily_low(lat, lon, parsed.target_date)
        except Exception:  # noqa: BLE001 - degrade to Open-Meteo-only on any NWS failure
            return None
        return None

    def _ensemble_member_values(self, lat: float, lon: float, parsed) -> list[float] | None:
        """One value per ensemble member for the market's variable, or None when unavailable."""
        key = (lat, lon, parsed.target_date)
        if key not in self._ensemble_cache:
            try:
                self._ensemble_cache[key] = self.open_meteo.ensemble_hourly_temperatures(
                    lat, lon, parsed.target_date, self.settings.ensemble_sigma_models
                )
            except Exception:  # noqa: BLE001 - ensemble API failure degrades to static sigma
                self._ensemble_cache[key] = None
        members = self._ensemble_cache[key]
        if not members:
            return None
        if parsed.variable == WeatherVariable.POINT_TEMP_F:
            if parsed.target_hour is None:
                return None
            return [m[parsed.target_hour] for m in members.values() if parsed.target_hour in m]
        # Daily high/low: per-member extreme, requiring near-full-day member coverage so a
        # truncated series cannot fake a tight spread.
        values: list[float] = []
        for member in members.values():
            if len(member) >= 20:
                values.append(max(member.values()) if parsed.variable == WeatherVariable.HIGH_TEMP_F else min(member.values()))
        return values
