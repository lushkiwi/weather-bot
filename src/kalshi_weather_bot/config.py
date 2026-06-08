from __future__ import annotations

from datetime import date

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment/.env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    kalshi_api_key_id: str | None = Field(default=None, alias="KALSHI_API_KEY_ID")
    kalshi_private_key_path: str | None = Field(default=None, alias="KALSHI_PRIVATE_KEY_PATH")
    kalshi_private_key: str | None = Field(default=None, alias="KALSHI_PRIVATE_KEY")
    kalshi_base_url: str = Field(
        default="https://demo-api.kalshi.co/trade-api/v2",
        alias="KALSHI_BASE_URL",
    )
    kalshi_market_limit: int = Field(default=50, alias="KALSHI_MARKET_LIMIT")
    # Hosted Postgres/Supabase connection string. When set, the SQLite-backed Store switches to
    # Postgres (see storage.py). Leave blank to use the local SQLite file for development.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    kalshi_shadow_base_url: str = Field(
        default="https://external-api.kalshi.com/trade-api/v2",
        alias="KALSHI_SHADOW_BASE_URL",
    )
    # Production read-only credentials for shadow tracking. The production/external API will
    # reject demo keys, so these are usually required. They fall back to the primary keys.
    kalshi_shadow_api_key_id: str | None = Field(default=None, alias="KALSHI_SHADOW_API_KEY_ID")
    kalshi_shadow_private_key_path: str | None = Field(default=None, alias="KALSHI_SHADOW_PRIVATE_KEY_PATH")
    kalshi_shadow_private_key: str | None = Field(default=None, alias="KALSHI_SHADOW_PRIVATE_KEY")
    kalshi_series_tickers: str = Field(
        default=(
            "KXTEMPNYCH,KXTEMPCHIH,KXTEMPBOSH,KXTEMPDCH,KXTEMPLAXH,KXTEMPMIAH,"
            "KXHIGHAUS,KXHIGHCHI,KXHIGHDEN,KXHIGHHOU,KXPHILHIGH,KXHIGHTSEA,KXHIGHTSFO,"
            "KXHIGHNY,KXHIGHMIA,KXLOWTAUS,KXLOWTCHI,KXLOWTBOS,KXLOWNYC,KXLOWLAX,"
            "KXRAINAUSM,KXRAINCHIM,KXRAINDALM,KXRAINHOUM,KXRAINLAXM,KXRAINMIAM,KXRAINNYC"
        ),
        alias="KALSHI_SERIES_TICKERS",
    )
    min_edge_cents: float = Field(default=3.0, alias="MIN_EDGE_CENTS")
    user_agent: str = Field(default="kalshi-weather-bot/0.1", alias="USER_AGENT")

    # --- Forecast-quality risk controls (added 2026-05-28 after shadow losses) ---
    # Place at most the single highest fee-adjusted-EV order per event (one city/date/hour
    # strike ladder). The strikes within an event are ~perfectly correlated, so stacking many
    # bets turns one wrong forecast into N simultaneous losses. See PROJECT_STATUS.md.
    best_strike_per_event: bool = Field(default=True, alias="BEST_STRIKE_PER_EVENT")
    # Skip a temperature market when the forecast standard deviation is >= this ratio times the
    # strike spacing: the forecast cannot resolve adjacent strikes, so any apparent edge is noise.
    # Default 1.0 means "skip when sigma >= strike spacing". Raise it to keep trading (and
    # collecting shadow-fill data) on markets the model cannot really call.
    forecast_uncertainty_gate_ratio: float = Field(default=1.0, alias="FORECAST_UNCERTAINTY_GATE_RATIO")
    # Assumed spacing (in degrees F) between one-sided ``-T`` ladder strikes when the market is
    # not an explicit band. Band markets use their own width instead.
    default_strike_spacing_f: float = Field(default=1.0, alias="DEFAULT_STRIKE_SPACING_F")

    # --- Data-driven model calibration (added 2026-06-08 after negative shadow review) ---
    # Apply a rolling residual correction keyed by series/station, weather variable, and (for
    # hourly temperature) target hour. The correction uses only already-settled ledger rows; when
    # there are too few samples, the raw Open-Meteo forecast is used unchanged.
    enable_forecast_bias_correction: bool = Field(default=True, alias="ENABLE_FORECAST_BIAS_CORRECTION")
    forecast_bias_min_samples: int = Field(default=3, alias="FORECAST_BIAS_MIN_SAMPLES")
    forecast_bias_lookback_days: int = Field(default=45, alias="FORECAST_BIAS_LOOKBACK_DAYS")
    forecast_bias_max_adjustment_f: float = Field(default=6.0, alias="FORECAST_BIAS_MAX_ADJUSTMENT_F")
    # Shadow rows include the real production-market evidence; local paper rows are useful for
    # development. "both" is safest locally, while cloud shadow-only effectively means shadow.
    forecast_bias_source: str = Field(default="both", alias="FORECAST_BIAS_SOURCE")
    forecast_bias_include_lookahead: bool = Field(default=False, alias="FORECAST_BIAS_INCLUDE_LOOKAHEAD")

    # Inflate sigma from realized residual RMSE where enough rows exist. This deliberately only
    # widens the hardcoded baseline; it never narrows sigma from a small/noisy sample.
    enable_dynamic_sigma: bool = Field(default=True, alias="ENABLE_DYNAMIC_SIGMA")
    dynamic_sigma_min_samples: int = Field(default=5, alias="DYNAMIC_SIGMA_MIN_SAMPLES")
    dynamic_sigma_multiplier: float = Field(default=1.75, alias="DYNAMIC_SIGMA_MULTIPLIER")
    dynamic_sigma_max_f: float = Field(default=14.0, alias="DYNAMIC_SIGMA_MAX_F")
    dynamic_sigma_source: str = Field(default="both", alias="DYNAMIC_SIGMA_SOURCE")
    dynamic_sigma_include_lookahead: bool = Field(default=False, alias="DYNAMIC_SIGMA_INCLUDE_LOOKAHEAD")

    stale_unsettled_grace_hours: int = Field(default=6, alias="STALE_UNSETTLED_GRACE_HOURS")

    # --- Bounded shadow-only data-collection experiment (added 2026-05-30) ---
    # The conservative gate above (ratio 1.0 vs ~1 F strike spacing) is unsatisfiable for every
    # 1 F-spaced temperature ladder given the widened sigma (4.5-5.0 F), so the read-only shadow
    # tracker records ~zero settled temperature fills and the model can never gather data to
    # recalibrate. These two settings relax the gate FOR SHADOW ONLY (paper/demo stay at the
    # conservative ratio) for a time-boxed window, then auto-revert. The other forecast-quality
    # controls (MIN_TRADE_PROBABILITY, EV gate, BEST_STRIKE_PER_EVENT, per-event caps) stay in
    # force, so even relaxed the gate lets only one best strike per event through to shadow.
    shadow_forecast_uncertainty_gate_ratio: float = Field(
        default=6.0, alias="SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO"
    )
    # ISO date (YYYY-MM-DD). While today's date is on or before this, the shadow tracker uses
    # the relaxed ratio above; once it has passed, shadow falls back to the conservative base
    # ``forecast_uncertainty_gate_ratio``. A forgotten relaxed gate cannot persist. Set empty to
    # disable the experiment immediately.
    shadow_gate_experiment_until: str = Field(default="2026-06-06", alias="SHADOW_GATE_EXPERIMENT_UNTIL")

    def effective_shadow_gate_ratio(self, today: date | None = None) -> float:
        """Gate ratio the shadow tracker should use right now.

        Returns the relaxed experiment ratio while within the bounded window, otherwise the
        conservative base ratio. An unset/invalid/expired window falls back to the base ratio so
        the relaxed gate can never silently outlive its window.
        """
        until_raw = (self.shadow_gate_experiment_until or "").strip()
        if not until_raw:
            return self.forecast_uncertainty_gate_ratio
        try:
            until = date.fromisoformat(until_raw)
        except ValueError:
            return self.forecast_uncertainty_gate_ratio
        current = today or date.today()
        if current <= until:
            return self.shadow_forecast_uncertainty_gate_ratio
        return self.forecast_uncertainty_gate_ratio

    def series_ticker_list(self) -> list[str]:
        return [ticker.strip().upper() for ticker in self.kalshi_series_tickers.split(",") if ticker.strip()]

    def require_kalshi_auth(self) -> None:
        if not self.kalshi_api_key_id:
            raise RuntimeError("Missing KALSHI_API_KEY_ID")
        if not (self.kalshi_private_key_path or self.kalshi_private_key):
            raise RuntimeError("Missing KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY")
