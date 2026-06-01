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
