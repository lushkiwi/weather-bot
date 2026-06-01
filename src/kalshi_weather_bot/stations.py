from __future__ import annotations

"""Settlement-station coordinate/source mapping.

Kalshi weather markets settle on a specific station/provider (e.g. NYC hourly temp on
AccuWeather at Central Park; Chicago daily high on the NWS report for Midway), not on a
city centroid. Forecasting with the exact settlement coordinates removes a large chunk of
the grid-vs-station basis. Series not listed here fall back to name geocoding.

Keyed by the series-ticker prefix (the portion before the first '-').
"""

# prefix -> (latitude, longitude, source_label)
STATIONS: dict[str, tuple[float, float, str]] = {
    # NYC Central Park, AccuWeather point used by KXTEMP NYC hourly markets.
    "KXTEMPNYCH": (40.7812, -73.9665, "AccuWeather Central Park, NYC"),
    "KXHIGHNY": (40.7812, -73.9665, "NWS Central Park, NYC"),
    "KXLOWNYC": (40.7812, -73.9665, "NWS Central Park, NYC"),
    # Chicago Midway (MDW), NWS Climatological Report.
    "KXHIGHCHI": (41.786, -87.752, "NWS Chicago Midway (MDW)"),
    "KXLOWTCHI": (41.786, -87.752, "NWS Chicago Midway (MDW)"),
    "KXTEMPCHIH": (41.786, -87.752, "NWS Chicago Midway (MDW)"),
}


def _series_prefix(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def station_for_ticker(ticker: str) -> tuple[float, float, str] | None:
    """Return (lat, lon, source_label) for a ticker's settlement station, if known."""
    return STATIONS.get(_series_prefix(ticker))
