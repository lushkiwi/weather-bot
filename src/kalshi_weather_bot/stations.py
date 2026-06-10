from __future__ import annotations

"""Settlement-station coordinate/source mapping.

Kalshi weather markets settle on a specific station/provider (e.g. NYC hourly temp on
AccuWeather at Central Park; Chicago daily high on the NWS report for Midway), not on a
city centroid. Forecasting with the exact settlement coordinates removes a large chunk of
the grid-vs-station basis. Series not listed here fall back to name geocoding.

Sources were verified 2026-06-10 against each series' ``settlement_sources`` in the Kalshi
API (``GET /trade-api/v2/series/{ticker}``): the daily temperature series link the NWS
Climatological Report for a station code (e.g. Austin = ``issuedby=AUS`` which is
Austin-Bergstrom, NOT Camp Mabry; Chicago daily = MDW Midway), and the hourly series link
AccuWeather METAR pages for a station (Chicago hourly = KORD O'Hare, not Midway). The
monthly rain series list only a generic weather.gov source, so those entries are marked
"assumed" — they reuse the station Kalshi chose for the same city's temperature markets and
must be re-verified against the market rules before being trusted for anything
settlement-critical.

Keyed by the series-ticker prefix (the portion before the first '-').
"""

# prefix -> (latitude, longitude, source_label)
STATIONS: dict[str, tuple[float, float, str]] = {
    # --- Hourly temperature (AccuWeather METAR per Kalshi settlement_sources) ---
    "KXTEMPNYCH": (40.7812, -73.9665, "AccuWeather Central Park, NYC (KNYC)"),
    "KXTEMPCHIH": (41.9797, -87.9044, "AccuWeather Chicago O'Hare (KORD)"),
    "KXTEMPBOSH": (42.3606, -71.0097, "AccuWeather Boston Logan (KBOS)"),
    "KXTEMPDCH": (38.8483, -77.0341, "AccuWeather Washington Reagan (KDCA)"),
    # Kalshi's source URL for this series anomalously points at KNYC; KLAX assumed from the title.
    "KXTEMPLAXH": (33.9381, -118.3866, "AccuWeather Los Angeles Intl (KLAX, assumed)"),
    "KXTEMPMIAH": (25.7906, -80.3164, "AccuWeather Miami Intl (KMIA)"),

    # --- Daily high temperature (NWS Climatological Report; station from issuedby code) ---
    "KXHIGHNY": (40.7812, -73.9665, "NWS CLI Central Park, NYC"),
    "KXHIGHCHI": (41.786, -87.752, "NWS CLI Chicago Midway (KMDW)"),
    "KXHIGHAUS": (30.1831, -97.6799, "NWS CLI Austin-Bergstrom Intl (KAUS)"),
    "KXHIGHDEN": (39.8466, -104.6562, "NWS CLI Denver Intl (KDEN)"),
    "KXHIGHHOU": (29.6375, -95.2825, "NWS CLI Houston Hobby (KHOU)"),
    "KXPHILHIGH": (39.8683, -75.2311, "NWS CLI Philadelphia Intl (KPHL)"),
    "KXHIGHTSEA": (47.4444, -122.3138, "NWS CLI Seattle-Tacoma Intl (KSEA)"),
    "KXHIGHTSFO": (37.6197, -122.3647, "NWS CLI San Francisco Intl (KSFO)"),
    "KXHIGHMIA": (25.7906, -80.3164, "NWS CLI Miami Intl (KMIA)"),

    # --- Daily low temperature (NWS Climatological Report) ---
    "KXLOWNYC": (40.7812, -73.9665, "NWS CLI Central Park, NYC"),
    "KXLOWTCHI": (41.786, -87.752, "NWS CLI Chicago Midway (KMDW)"),
    "KXLOWTAUS": (30.1831, -97.6799, "NWS CLI Austin-Bergstrom Intl (KAUS)"),
    "KXLOWTBOS": (42.3606, -71.0097, "NWS CLI Boston Logan (KBOS)"),
    "KXLOWLAX": (33.9381, -118.3866, "NWS CLI Los Angeles Intl (KLAX, assumed)"),

    # --- Rain (Kalshi lists only a generic weather.gov source for the monthly series; the
    # station is assumed to match the same city's temperature markets — verify before relying
    # on these for anything settlement-critical) ---
    "KXRAINNYC": (40.7812, -73.9665, "NWS CLI Central Park, NYC"),
    "KXRAINAUSM": (30.1831, -97.6799, "NWS Austin-Bergstrom Intl (KAUS, assumed)"),
    "KXRAINCHIM": (41.786, -87.752, "NWS Chicago Midway (KMDW, assumed)"),
    "KXRAINDALM": (32.8979, -97.0219, "NWS Dallas-Fort Worth Intl (KDFW, assumed)"),
    "KXRAINHOUM": (29.6375, -95.2825, "NWS Houston Hobby (KHOU, assumed)"),
    "KXRAINLAXM": (33.9381, -118.3866, "NWS Los Angeles Intl (KLAX, assumed)"),
    "KXRAINMIAM": (25.7906, -80.3164, "NWS Miami Intl (KMIA, assumed)"),
}


def _series_prefix(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def station_for_ticker(ticker: str) -> tuple[float, float, str] | None:
    """Return (lat, lon, source_label) for a ticker's settlement station, if known."""
    return STATIONS.get(_series_prefix(ticker))
