from __future__ import annotations

import math
from datetime import date

from .models import ForecastEstimate, WeatherVariable


def estimate_probability(
    mean: float,
    threshold: float,
    variable: WeatherVariable,
    target_date: date,
    comparator: str | None = ">=",
    band_lower: float | None = None,
    band_upper: float | None = None,
    direct_probability: float | None = None,
    sigma_override: float | None = None,
    source_suffix: str | None = None,
) -> ForecastEstimate:
    sigma = sigma_override if sigma_override is not None else _sigma(variable, target_date)
    if direct_probability is not None:
        # Used for "any rain" markets where a forecast precipitation probability is more
        # appropriate than a Gaussian on a zero-inflated, right-skewed rain amount.
        probability_yes = direct_probability if comparator != "<" else 1.0 - direct_probability
        probability_yes = min(max(probability_yes, 0.01), 0.99)
        source = "open-meteo-precip-probability"
        if source_suffix:
            source = f"{source}+{source_suffix}"
        return ForecastEstimate(mean=mean, sigma=sigma, probability_yes=probability_yes, source=source)
    if band_lower is not None and band_upper is not None:
        # Bucket markets resolve YES only when the outcome lands inside [lower, upper).
        # P = Phi((upper - mean)/sigma) - Phi((lower - mean)/sigma); edges already carry
        # the continuity correction from the parser.
        probability_yes = _normal_cdf((band_upper - mean) / sigma) - _normal_cdf((band_lower - mean) / sigma)
        source = "open-meteo-baseline-normal-band"
    else:
        z = (threshold - mean) / sigma
        p_ge = 1.0 - _normal_cdf(z)
        probability_yes = p_ge if comparator != "<" else 1.0 - p_ge
        source = "open-meteo-baseline-normal"
    probability_yes = min(max(probability_yes, 0.01), 0.99)
    if source_suffix:
        source = f"{source}+{source_suffix}"
    return ForecastEstimate(
        mean=mean,
        sigma=sigma,
        probability_yes=probability_yes,
        source=source,
    )


def base_sigma(variable: WeatherVariable, target_date: date) -> float:
    """Public baseline sigma before settled-ledger dynamic widening."""
    return _sigma(variable, target_date)


def _sigma(variable: WeatherVariable, target_date: date) -> float:
    """Forecast standard deviation in the variable's units.

    Recalibrated 2026-05-28 from realized shadow forecast errors. The first settled
    KXTEMPNYCH hourly fills missed the Central Park settlement value by 1.3-3.3 F even at
    ~45-60 min lead, and that is on top of an Open-Meteo-grid vs settlement-station basis.
    The previous lead-0 hourly sigma (2.5 F) put those misses 1-3 sigma out, which fabricated
    high-conviction edges on the wrong side. These wider values keep near-the-money
    probabilities closer to 0.5 so a forecast miss no longer reads as a near-certainty.
    Tune from `kalshi-weather-calib` forecast MAE/RMSE as more data settles.
    """
    lead_days = max((target_date - date.today()).days, 0)
    if variable == WeatherVariable.POINT_TEMP_F:
        return min(4.5 + 0.9 * lead_days, 11.0)
    if variable in {WeatherVariable.HIGH_TEMP_F, WeatherVariable.LOW_TEMP_F}:
        return min(5.0 + 1.0 * lead_days, 13.0)
    if variable in {WeatherVariable.RAIN_IN, WeatherVariable.SNOW_IN}:
        return min(0.25 + 0.10 * lead_days, 1.5)
    return 6.0


def strike_spacing(band_lower: float | None, band_upper: float | None, default_spacing: float) -> float:
    """Distance between adjacent resolvable strikes, used by the uncertainty gate.

    Band markets resolve inside an explicit interval, so their width is the spacing; one-sided
    ``-T`` ladder strikes use the configured default (Kalshi temperature ladders step ~1 F).
    """
    if band_lower is not None and band_upper is not None:
        width = band_upper - band_lower
        if width > 0:
            return width
    return default_spacing


def forecast_resolves_strikes(sigma: float, spacing: float, ratio: float) -> bool:
    """True when the forecast is precise enough to distinguish adjacent strikes.

    When ``sigma >= ratio * spacing`` the point forecast cannot tell one strike from the next,
    so any modelled edge is an artifact of forecast noise rather than a tradeable mispricing.
    """
    if spacing is None or spacing <= 0:
        return True
    return sigma < ratio * spacing


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
