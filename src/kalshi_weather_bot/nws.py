from __future__ import annotations

"""NWS (api.weather.gov) point-forecast client.

Kalshi daily temperature markets settle on the NWS Climatological Report for a specific
station, so the NWS's own point forecast for that station is the settlement-source-matched
forecast; Open-Meteo is a different model on a different grid. The scan blends the two
(`NWS_FORECAST_WEIGHT`) to cut the source-basis error that dominated past losses.

api.weather.gov is free/keyless but flaky; every method is best-effort and returns None on
failure so a NWS outage degrades to the pure Open-Meteo forecast instead of failing scans.
"""

from datetime import date
from typing import Any

import requests

from .config import Settings

BASE_URL = "https://api.weather.gov"
# After this many consecutive fetch failures, stop trying new locations for the rest of the
# process (the cloud cron is a fresh process every run, so an NWS outage self-heals).
MAX_CONSECUTIVE_ERRORS = 3


class NWSClient:
    def __init__(self, settings: Settings):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"{settings.user_agent} (research bot)",
                "Accept": "application/geo+json",
            }
        )
        self._period_cache: dict[tuple[float, float], list[dict[str, Any]] | None] = {}
        self._consecutive_errors = 0

    def hourly_temperature(self, lat: float, lon: float, target_date: date, target_hour: int) -> float | None:
        prefix = f"{target_date.isoformat()}T{target_hour:02d}"
        for period in self._hourly_periods(lat, lon):
            if str(period.get("startTime") or "").startswith(prefix):
                return _temperature_f(period)
        return None

    def daily_high(self, lat: float, lon: float, target_date: date) -> float | None:
        temps = self._temps_for_date(lat, lon, target_date)
        return max(temps) if temps else None

    def daily_low(self, lat: float, lon: float, target_date: date) -> float | None:
        temps = self._temps_for_date(lat, lon, target_date)
        return min(temps) if temps else None

    def _temps_for_date(self, lat: float, lon: float, target_date: date) -> list[float]:
        prefix = f"{target_date.isoformat()}T"
        temps = [
            t
            for period in self._hourly_periods(lat, lon)
            if str(period.get("startTime") or "").startswith(prefix)
            and (t := _temperature_f(period)) is not None
        ]
        # A partial day (same-day scan or end of the ~6.5-day horizon) would bias a max/min;
        # require near-full coverage before claiming a daily high/low.
        return temps if len(temps) >= 18 else []

    def _hourly_periods(self, lat: float, lon: float) -> list[dict[str, Any]]:
        key = (round(lat, 4), round(lon, 4))
        if key in self._period_cache:
            return self._period_cache[key] or []
        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            return []
        try:
            points = self.session.get(f"{BASE_URL}/points/{key[0]:.4f},{key[1]:.4f}", timeout=10)
            points.raise_for_status()
            forecast_url = (points.json().get("properties") or {}).get("forecastHourly")
            if not forecast_url:
                raise ValueError("no forecastHourly url")
            forecast = self.session.get(forecast_url, params={"units": "us"}, timeout=15)
            forecast.raise_for_status()
            periods = (forecast.json().get("properties") or {}).get("periods") or []
        except Exception:  # noqa: BLE001 - NWS outage must degrade, not break the scan
            self._consecutive_errors += 1
            self._period_cache[key] = None
            return []
        self._consecutive_errors = 0
        self._period_cache[key] = periods
        return periods


def _temperature_f(period: dict[str, Any]) -> float | None:
    try:
        value = float(period["temperature"])
    except (KeyError, TypeError, ValueError):
        return None
    if str(period.get("temperatureUnit") or "F").upper() == "C":
        return value * 9.0 / 5.0 + 32.0
    return value
