from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from .models import ParsedWeatherMarket, WeatherVariable

CITY_PATTERNS = [
    re.compile(r"in ([A-Z][A-Za-z .'-]+?)(?: be | on | by | at |\?|$)", re.I),
    re.compile(r"for ([A-Z][A-Za-z .'-]+?)(?: be | on | by | at |\?|$)", re.I),
]

DATE_PATTERNS = [
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d",
    "%B %d",
    "%Y-%m-%d",
]


def parse_market(market: dict[str, Any]) -> ParsedWeatherMarket | None:
    ticker = str(market.get("ticker") or "")
    title = " ".join(
        str(market.get(k) or "")
        for k in ("title", "subtitle", "yes_sub_title", "no_sub_title", "rules_primary")
    ).strip()
    haystack = title.lower()
    if not ticker or not any(w in haystack for w in ("temperature", "rain", "snow", "weather", "high", "low")):
        return None

    notes: list[str] = []
    variable = WeatherVariable.UNKNOWN
    if re.search(r"\bhigh\b", haystack) and ("temp" in haystack or "temperature" in haystack):
        variable = WeatherVariable.HIGH_TEMP_F
    elif re.search(r"\blow\b", haystack) and ("temp" in haystack or "temperature" in haystack):
        variable = WeatherVariable.LOW_TEMP_F
    elif "temp" in haystack or "temperature" in haystack:
        variable = WeatherVariable.POINT_TEMP_F
    elif "rain" in haystack or "precip" in haystack:
        variable = WeatherVariable.RAIN_IN
    elif "snow" in haystack:
        variable = WeatherVariable.SNOW_IN

    threshold, comparator = _parse_threshold(title, variable)
    city = _parse_city(title)
    target_date = _parse_date(title) or _date_from_ticker(ticker)
    target_hour = _parse_hour(title)

    # Bands (e.g. "66-67°", ticker -B66.5) resolve YES only inside a range, not one-sided.
    # Prefer the strike encoded in the ticker, refined by the explicit integer range in the title.
    band_lower = band_upper = None
    strike = parse_strike_from_ticker(ticker)
    if strike and strike[0] == "band":
        band_lower, band_upper = strike[1], strike[2]
        title_band = _parse_title_band(title)
        if title_band:
            band_lower, band_upper = title_band
        if threshold is None:
            threshold = band_lower
    elif strike and strike[0] == "threshold":
        # The ticker carries the actual strike; trust it over the first number in the title.
        threshold = strike[1]

    confidence = 0.25
    if variable != WeatherVariable.UNKNOWN:
        confidence += 0.25
    if threshold is not None:
        confidence += 0.2
    if city:
        confidence += 0.15
    if target_date:
        confidence += 0.15
    if variable == WeatherVariable.POINT_TEMP_F and target_hour is None:
        notes.append("hour_not_parsed")
    if not city:
        notes.append("city_not_parsed")
    if threshold is None:
        notes.append("threshold_not_parsed")
    if target_date is None:
        notes.append("date_not_parsed")

    return ParsedWeatherMarket(
        ticker=ticker,
        title=title or ticker,
        city=city,
        target_date=target_date,
        target_hour=target_hour,
        variable=variable,
        threshold=threshold,
        comparator=comparator,
        confidence=min(confidence, 1.0),
        band_lower=band_lower,
        band_upper=band_upper,
        notes=tuple(notes),
    )


def parse_strike_from_ticker(ticker: str) -> tuple[str, float, float | None] | None:
    """Extract the strike encoded in a Kalshi weather ticker suffix.

    Returns ("band", lower, upper) for ``-B##.#`` bucket markets (continuous edges,
    assuming a 2-integer-wide bucket), or ("threshold", value, None) for ``-T##`` tail
    markets. Returns None when no strike suffix is present.
    """
    match = re.search(r"-([BT])(-?\d+(?:\.\d+)?)$", ticker)
    if not match:
        return None
    value = float(match.group(2))
    if match.group(1) == "B":
        # A band centered near ``value`` covering two integer degrees, e.g. B66.5 -> {66,67}
        # -> continuous [65.5, 67.5). The title range refines this when available.
        return ("band", value - 1.0, value + 1.0)
    return ("threshold", value, None)


def _parse_title_band(text: str) -> tuple[float, float] | None:
    """Read an explicit integer range like "66-67°" / "66° to 67°" as continuous edges."""
    match = re.search(r"(\d+)\s*°?\s*(?:-|–|to)\s*(\d+)\s*°", text)
    if not match:
        return None
    lo, hi = int(match.group(1)), int(match.group(2))
    if hi < lo:
        return None
    # Integer labels {lo..hi} map to the continuous interval [lo-0.5, hi+0.5).
    return float(lo) - 0.5, float(hi) + 0.5


def _parse_threshold(text: str, variable: WeatherVariable) -> tuple[float | None, str | None]:
    comparator = None
    if re.search(r"\b(at least|above|over|greater than|higher than)\b", text, re.I):
        comparator = ">="
    elif re.search(r"\b(below|under|less than|lower than)\b", text, re.I):
        comparator = "<"
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:°|degrees|deg|f|inches|inch|in\b)?", text, re.I)
    if not match:
        return None, comparator
    value = float(match.group(1))
    if variable in {WeatherVariable.RAIN_IN, WeatherVariable.SNOW_IN} and value > 10:
        # Many precipitation markets use hundredths/tenths in wording; leave a note via conservative no-parse.
        return None, comparator
    return value, comparator or ">="


def _parse_city(text: str) -> str | None:
    for pattern in CITY_PATTERNS:
        match = pattern.search(text)
        if match:
            city = match.group(1).strip(" .?,-")
            # Drop common non-city captures.
            if city.lower() not in {"the", "a", "weather"}:
                return city
    return None


def _parse_hour(text: str) -> int | None:
    match = re.search(r"\bat\s+(\d{1,2})(?::\d{2})?\s*(am|pm)\b", text, re.I)
    if not match:
        return None
    hour = int(match.group(1)) % 12
    if match.group(2).lower() == "pm":
        hour += 12
    return hour


def _parse_date(text: str) -> date | None:
    year = date.today().year
    for match in re.finditer(r"\b[A-Z][a-z]+ \d{1,2}(?:, \d{4})?\b|\b\d{4}-\d{2}-\d{2}\b", text):
        raw = match.group(0)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            candidates = [(raw, "%Y-%m-%d")]
        elif "," in raw:
            candidates = [(raw, "%b %d, %Y"), (raw, "%B %d, %Y")]
        else:
            candidates = [(f"{raw}, {year}", "%b %d, %Y"), (f"{raw}, {year}", "%B %d, %Y")]
        for candidate, fmt in candidates:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def _date_from_ticker(ticker: str) -> date | None:
    match = re.search(r"(\d{2})([A-Z]{3})(\d{2})", ticker)
    if not match:
        return None
    yy, mon, dd = match.groups()
    try:
        return datetime.strptime(f"20{yy}-{mon}-{dd}", "%Y-%b-%d").date()
    except ValueError:
        return None
