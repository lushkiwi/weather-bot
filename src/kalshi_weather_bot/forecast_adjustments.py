from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .config import Settings
from .models import WeatherVariable


@dataclass(frozen=True)
class ForecastAdjustment:
    raw_mean: float
    adjusted_mean: float
    sigma: float
    bias_correction: float = 0.0
    bias_samples: int = 0
    bias_mae: float | None = None
    sigma_samples: int = 0
    sigma_rmse: float | None = None

    @property
    def used_bias_correction(self) -> bool:
        return self.bias_samples > 0 and self.bias_correction != 0.0

    @property
    def used_dynamic_sigma(self) -> bool:
        return self.sigma_samples > 0 and self.sigma_rmse is not None


def apply_forecast_adjustments(
    *,
    store: Any,
    settings: Settings,
    ticker: str,
    variable: WeatherVariable,
    target_date: date,
    target_hour: int | None,
    raw_mean: float,
    base_sigma: float,
) -> ForecastAdjustment:
    """Apply settled-ledger calibration to a raw forecast.

    The corrections are deliberately conservative:
    - bias correction only activates after ``FORECAST_BIAS_MIN_SAMPLES`` rows for the exact
      series/variable/hour key (hour is used for POINT_TEMP_F);
    - the adjustment is clipped to ``FORECAST_BIAS_MAX_ADJUSTMENT_F``;
    - dynamic sigma widens at ``DYNAMIC_SIGMA_MIN_SAMPLES``, but narrowing below the baseline
      needs the larger ``DYNAMIC_SIGMA_NARROW_MIN_SAMPLES`` of verified non-lookahead errors
      and is floored at ``DYNAMIC_SIGMA_MIN_F``.
    """
    series_ticker = _series_prefix(ticker)
    hour_key = target_hour if variable == WeatherVariable.POINT_TEMP_F else None
    adjusted = raw_mean
    bias_correction = 0.0
    bias_samples = 0
    bias_mae: float | None = None

    if settings.enable_forecast_bias_correction:
        stats = store.forecast_error_stats(
            series_ticker=series_ticker,
            variable=variable.value,
            target_hour=hour_key,
            source=settings.forecast_bias_source,
            lookback_days=settings.forecast_bias_lookback_days,
            include_lookahead=settings.forecast_bias_include_lookahead,
        )
        bias_samples = int(stats.get("n") or 0)
        bias = stats.get("bias")
        if bias_samples >= settings.forecast_bias_min_samples and bias is not None:
            max_adjust = abs(settings.forecast_bias_max_adjustment_f)
            bias_correction = max(-max_adjust, min(max_adjust, float(bias)))
            # Error = forecast - realized, so subtracting positive bias cools the forecast.
            adjusted = raw_mean - bias_correction
            bias_mae = float(stats["mae"]) if stats.get("mae") is not None else None

    sigma = base_sigma
    sigma_samples = 0
    sigma_rmse: float | None = None
    if settings.enable_dynamic_sigma:
        stats = store.forecast_error_stats(
            series_ticker=series_ticker,
            variable=variable.value,
            target_hour=hour_key,
            source=settings.dynamic_sigma_source,
            lookback_days=settings.forecast_bias_lookback_days,
            include_lookahead=settings.dynamic_sigma_include_lookahead,
        )
        sigma_samples = int(stats.get("n") or 0)
        rmse = stats.get("rmse")
        if sigma_samples >= settings.dynamic_sigma_min_samples and rmse is not None:
            sigma_rmse = float(rmse)
            calibrated = sigma_rmse * settings.dynamic_sigma_multiplier
            if calibrated >= base_sigma:
                sigma = min(settings.dynamic_sigma_max_f, calibrated)
            elif (
                settings.dynamic_sigma_allow_narrowing
                and not settings.dynamic_sigma_include_lookahead
                and sigma_samples >= settings.dynamic_sigma_narrow_min_samples
            ):
                # Narrowing is how verified evidence can ever reopen the uncertainty gate, so it
                # demands a larger clean (non-lookahead) sample and keeps a hard floor.
                sigma = max(settings.dynamic_sigma_min_f, calibrated)
            else:
                sigma_rmse = None  # not enough clean evidence to narrow; keep the baseline

    return ForecastAdjustment(
        raw_mean=raw_mean,
        adjusted_mean=adjusted,
        sigma=sigma,
        bias_correction=bias_correction,
        bias_samples=bias_samples if bias_correction else 0,
        bias_mae=bias_mae,
        sigma_samples=sigma_samples if sigma_rmse is not None else 0,
        sigma_rmse=sigma_rmse,
    )


def _series_prefix(ticker: str) -> str:
    return ticker.split("-", 1)[0]
