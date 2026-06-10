from __future__ import annotations

from datetime import date
from typing import Any

import requests

from .config import Settings
from .models import WeatherVariable


class OpenMeteoClient:
    def __init__(self, settings: Settings):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})

    def geocode(self, city: str) -> tuple[float, float, str] | None:
        resp = self.session.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        first = results[0]
        label = ", ".join(str(x) for x in (first.get("name"), first.get("admin1"), first.get("country_code")) if x)
        return float(first["latitude"]), float(first["longitude"]), label

    def daily_forecast(self, latitude: float, longitude: float, target_date: date) -> dict[str, Any] | None:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": "auto",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "rain_sum",
                "snowfall_sum",
                "precipitation_probability_max",
            ]),
        }
        resp = self.session.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
        resp.raise_for_status()
        daily = resp.json().get("daily") or {}
        if not daily.get("time"):
            return None
        return {k: (v[0] if isinstance(v, list) and v else v) for k, v in daily.items()}

    def ensemble_hourly_temperatures(
        self, latitude: float, longitude: float, target_date: date, models: str
    ) -> dict[str, dict[int, float]]:
        """Per-member hourly temperatures for one local day: member key -> {hour: temp_f}.

        Backed by the (free, keyless) Open-Meteo ensemble API. The spread across members is a
        day-specific forecast-uncertainty estimate, replacing the hardcoded climatological sigma
        when enough members report (see ForecastEngine.sigma_base).
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "hourly": "temperature_2m",
            "models": models,
        }
        resp = self.session.get("https://ensemble-api.open-meteo.com/v1/ensemble", params=params, timeout=20)
        resp.raise_for_status()
        hourly = resp.json().get("hourly") or {}
        times = hourly.get("time") or []
        members: dict[str, dict[int, float]] = {}
        for key, series in hourly.items():
            if key == "time" or not key.startswith("temperature_2m") or not isinstance(series, list):
                continue
            for timestamp, value in zip(times, series):
                if value is None:
                    continue
                try:
                    hour = int(str(timestamp)[11:13])
                    members.setdefault(key, {})[hour] = float(value)
                except (TypeError, ValueError):
                    continue
        return members

    def hourly_temperature(self, latitude: float, longitude: float, target_date: date, target_hour: int) -> float | None:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "hourly": "temperature_2m",
        }
        resp = self.session.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=20)
        resp.raise_for_status()
        hourly = resp.json().get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        suffix = f"T{target_hour:02d}:00"
        for timestamp, temp in zip(times, temps):
            if str(timestamp).endswith(suffix):
                try:
                    return float(temp)
                except (TypeError, ValueError):
                    return None
        return None


def value_for_variable(daily: dict[str, Any], variable: WeatherVariable) -> float | None:
    key = {
        WeatherVariable.POINT_TEMP_F: "temperature_2m_max",
        WeatherVariable.HIGH_TEMP_F: "temperature_2m_max",
        WeatherVariable.LOW_TEMP_F: "temperature_2m_min",
        WeatherVariable.RAIN_IN: "rain_sum",
        WeatherVariable.SNOW_IN: "snowfall_sum",
    }.get(variable)
    if not key:
        return None
    try:
        return float(daily[key])
    except (KeyError, TypeError, ValueError):
        return None
