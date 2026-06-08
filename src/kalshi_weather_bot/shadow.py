from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .fees import FeeModel
from .forecast_adjustments import apply_forecast_adjustments
from .kalshi_client import KalshiClient
from .market_parser import parse_market
from .models import WeatherVariable
from .orderbook import parse_market_quote, parse_orderbook
from .paper import TEMP_VARIABLES, TradeCandidate, _event_ticker, _is_lookahead
from .probability import base_sigma, estimate_probability, forecast_resolves_strikes, strike_spacing
from .safety import SafetyGuard
from .stations import station_for_ticker
from .storage import Store
from .weather import OpenMeteoClient, value_for_variable

PRODUCTION_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class ShadowRunResult:
    scan_id: int
    markets_seen: int
    snapshots_recorded: int
    shadow_orders_filled: int
    skipped_no_liquidity: int
    skipped_no_edge: int
    market_errors: int = 0


@dataclass(frozen=True)
class ShadowReconcileResult:
    markets_checked: int
    orders_settled: int


@dataclass
class _ShadowEvaluation:
    """A market's shadow snapshot payload + best candidate, computed without portfolio state."""

    snapshot: dict
    parsed: object
    event_ticker: str
    selected: TradeCandidate
    stateless_skip: str | None


class ProductionShadowTracker:
    """Read production Kalshi market data and simulate live-executable fills only.

    This class never submits orders. It intentionally uses a production/external
    market-data base URL while the rest of the bot may remain pointed at demo.
    """

    def __init__(
        self,
        settings: Settings,
        store: Store,
        quantity: int = 1,
        fee_model: FeeModel | None = None,
        production_base_url: str | None = None,
        safety_guard: SafetyGuard | None = None,
    ):
        self.settings = settings
        self.production_base_url = (production_base_url or settings.kalshi_shadow_base_url or PRODUCTION_BASE_URL).rstrip("/")
        # The production/external API rejects demo keys, so prefer dedicated shadow read
        # credentials when provided; otherwise fall back to the primary keys.
        prod_overrides: dict[str, str] = {"kalshi_base_url": self.production_base_url}
        if settings.kalshi_shadow_api_key_id:
            prod_overrides["kalshi_api_key_id"] = settings.kalshi_shadow_api_key_id
        if settings.kalshi_shadow_private_key_path:
            prod_overrides["kalshi_private_key_path"] = settings.kalshi_shadow_private_key_path
        if settings.kalshi_shadow_private_key:
            prod_overrides["kalshi_private_key"] = settings.kalshi_shadow_private_key
        prod_settings = settings.model_copy(update=prod_overrides)
        self.kalshi = KalshiClient(prod_settings)
        self.weather = OpenMeteoClient(settings)
        self.store = store
        self.quantity = quantity
        self.fee_model = fee_model or FeeModel()
        self.safety_guard = safety_guard or SafetyGuard()
        self._geo_cache: dict[str, tuple[float, float, str] | None] = {}
        self._hourly_cache: dict[tuple[float, float, object, int], float | None] = {}
        self._daily_cache: dict[tuple[float, float, object], dict | None] = {}

    def run_once(self, limit: int) -> ShadowRunResult:
        series_tickers = self.settings.series_ticker_list()
        notes = f"phase2_75_production_shadow series={len(series_tickers)} limit_per_series={limit} base_url={self.production_base_url}"
        scan_id = self.store.create_scan(limit, notes=notes)
        totals = {k: 0 for k in ("markets_seen", "snapshots", "fills", "no_liq", "no_edge", "market_errors")}

        market_iter = (
            market
            for series_ticker in series_tickers
            for market in self.kalshi.iter_markets(limit=limit, series_ticker=series_ticker)
        ) if series_tickers else self.kalshi.iter_markets(limit=limit)

        # Pass 1: evaluate every market without touching portfolio state.
        evaluations: list[_ShadowEvaluation] = []
        for market in market_iter:
            totals["markets_seen"] += 1
            try:
                evaluation = self._evaluate_market(market)
            except Exception as exc:  # noqa: BLE001
                totals["market_errors"] += 1
                self.store.insert_runner_event("error", f"shadow_market_error ticker={market.get('ticker')} {type(exc).__name__}: {exc}")
                continue
            if evaluation is not None:
                evaluations.append(evaluation)

        # Best-strike-per-event: only the single highest-EV tradeable strike in each correlated
        # ladder may become a shadow fill; the rest are recorded as snapshots but skipped.
        self._mark_best_strike_per_event(evaluations)

        # Pass 2: persist snapshots in evaluation order, applying stateful safety to survivors.
        for evaluation in evaluations:
            self._persist_evaluation(scan_id, evaluation, totals)

        return ShadowRunResult(
            scan_id,
            totals["markets_seen"],
            totals["snapshots"],
            totals["fills"],
            totals["no_liq"],
            totals["no_edge"],
            totals["market_errors"],
        )

    def _evaluate_market(self, market: dict) -> _ShadowEvaluation | None:
        """Build a market's shadow snapshot payload + best candidate without portfolio state."""
        if not _market_is_tradeable(market):
            return None
        parsed = parse_market(market)
        if not parsed or not self._usable(parsed):
            return None

        # Prefer the exact settlement-station coordinates over a city-name geocode.
        geo = station_for_ticker(parsed.ticker) or self._geocode(parsed.city or "")
        if not geo:
            return None

        forecast_value = self._forecast_value(geo[0], geo[1], parsed)
        if forecast_value is None:
            return None

        orderbook_payload = self.kalshi.get_orderbook(parsed.ticker)
        quote = parse_orderbook(orderbook_payload)
        depth = _depth_from_orderbook(orderbook_payload)
        market_quote = parse_market_quote(market)
        if quote.yes_ask is None:
            quote = market_quote
        yes_ask_size = depth["yes_ask_size"] or _float_or_zero(market.get("yes_ask_size_fp"))
        no_ask_size = depth["no_ask_size"] or _first_float(market.get("no_ask_size_fp"), market.get("yes_bid_size_fp"))

        adjustment = apply_forecast_adjustments(
            store=self.store,
            settings=self.settings,
            ticker=parsed.ticker,
            variable=parsed.variable,
            target_date=parsed.target_date,  # type: ignore[arg-type]
            target_hour=parsed.target_hour,
            raw_mean=forecast_value,
            base_sigma=base_sigma(parsed.variable, parsed.target_date),  # type: ignore[arg-type]
        )
        source_bits = []
        if adjustment.used_bias_correction:
            source_bits.append(f"bias_corrected_n{adjustment.bias_samples}")
        if adjustment.used_dynamic_sigma:
            source_bits.append(f"dynamic_sigma_n{adjustment.sigma_samples}")
        estimate = estimate_probability(
            mean=adjustment.adjusted_mean,
            threshold=parsed.threshold,  # type: ignore[arg-type]
            variable=parsed.variable,
            target_date=parsed.target_date,  # type: ignore[arg-type]
            comparator=parsed.comparator,
            band_lower=parsed.band_lower,
            band_upper=parsed.band_upper,
            direct_probability=self._rain_probability(geo[0], geo[1], parsed),
            sigma_override=adjustment.sigma,
            source_suffix="+".join(source_bits) if source_bits else None,
        )
        fair_yes = estimate.probability_yes * 100.0
        fair_no = (1.0 - estimate.probability_yes) * 100.0
        candidates = [
            self._candidate("BUY_YES", quote.yes_ask, yes_ask_size, estimate.probability_yes),
            self._candidate("BUY_NO", quote.no_ask, no_ask_size, 1.0 - estimate.probability_yes),
        ]
        liquid = [c for c in candidates if c.ask_size >= self.quantity and c.ask_cents is not None and c.ask_cents > 0]
        selected = max(liquid, key=lambda c: c.ev_cents if c.ev_cents is not None else -10_000.0) if liquid else max(candidates, key=lambda c: c.ev_cents if c.ev_cents is not None else -10_000.0)

        stateless_skip = None
        if not liquid:
            stateless_skip = "no_executable_production_liquidity"
        elif selected.ev_cents is None:
            stateless_skip = "missing_production_fee_adjusted_edge"
        elif self._fails_uncertainty_gate(parsed, estimate.sigma):
            stateless_skip = "forecast_uncertainty_exceeds_strike_spacing"
        elif selected.probability_win < self.safety_guard.settings.min_trade_probability:
            stateless_skip = "probability_below_min_trade_probability"

        snapshot = {
            "ticker": parsed.ticker,
            "title": parsed.title,
            "city": geo[2],
            "target_date": parsed.target_date.isoformat() if parsed.target_date else None,
            "target_hour": parsed.target_hour,
            "variable": parsed.variable.value,
            "threshold": parsed.threshold,
            "band_lower": parsed.band_lower,
            "band_upper": parsed.band_upper,
            "event_ticker": _event_ticker(parsed.ticker),
            "lookahead_risk": int(_is_lookahead(parsed)),
            "market_status": market.get("status"),
            "close_time": market.get("close_time"),
            "production_base_url": self.production_base_url,
            "raw_forecast_value": adjustment.raw_mean,
            "forecast_value": estimate.mean,
            "forecast_sigma": estimate.sigma,
            "model_source": estimate.source,
            "bias_correction": adjustment.bias_correction,
            "bias_correction_n": adjustment.bias_samples,
            "bias_mae": adjustment.bias_mae,
            "probability_yes": estimate.probability_yes,
            "fair_yes_cents": fair_yes,
            "fair_no_cents": fair_no,
            "yes_bid_cents": quote.yes_bid,
            "yes_ask_cents": quote.yes_ask,
            "yes_ask_size": yes_ask_size,
            "no_bid_cents": quote.no_bid,
            "no_ask_cents": quote.no_ask,
            "no_ask_size": no_ask_size,
            "spread_cents": _spread(quote.yes_bid, quote.yes_ask),
            "selected_side": selected.side,
            "selected_price_cents": selected.ask_cents,
            "edge_cents": (selected.fair_cents - selected.ask_cents) * self.quantity if selected.ask_cents is not None else None,
            "fee_cents": selected.fee_cents,
            "fee_adjusted_ev_cents": selected.ev_cents,
            "skipped_reason": None,
            "orderbook_json": orderbook_payload,
        }
        return _ShadowEvaluation(snapshot=snapshot, parsed=parsed, event_ticker=_event_ticker(parsed.ticker), selected=selected, stateless_skip=stateless_skip)

    def _fails_uncertainty_gate(self, parsed, sigma: float) -> bool:
        """True when the forecast cannot resolve adjacent strikes for a temperature market.

        Shadow is read-only (no orders), so it uses ``effective_shadow_gate_ratio`` — the relaxed
        ratio during the bounded data-collection window, the conservative base ratio otherwise.
        """
        if parsed.variable not in TEMP_VARIABLES:
            return False
        spacing = strike_spacing(parsed.band_lower, parsed.band_upper, self.settings.default_strike_spacing_f)
        return not forecast_resolves_strikes(sigma, spacing, self.settings.effective_shadow_gate_ratio())

    def _mark_best_strike_per_event(self, evaluations: list[_ShadowEvaluation]) -> None:
        if not self.settings.best_strike_per_event:
            return
        best: dict[str, _ShadowEvaluation] = {}
        for ev in evaluations:
            if ev.stateless_skip is not None:
                continue
            current = best.get(ev.event_ticker)
            if current is None or (ev.selected.ev_cents or -1e9) > (current.selected.ev_cents or -1e9):
                best[ev.event_ticker] = ev
        for ev in evaluations:
            if ev.stateless_skip is None and best.get(ev.event_ticker) is not ev:
                ev.stateless_skip = "not_best_strike_in_event"

    def _persist_evaluation(self, scan_id: int, ev: _ShadowEvaluation, totals: dict) -> None:
        parsed = ev.parsed
        selected = ev.selected
        skipped = ev.stateless_skip
        if skipped is None:
            safety = self.safety_guard.check(
                store=_ShadowSafetyView(self.store),
                ticker=parsed.ticker,
                side=selected.side,
                quantity=self.quantity,
                ask_cents=selected.ask_cents or 0.0,
                fee_adjusted_ev_cents=selected.ev_cents,
                default_min_ev_cents=self.settings.min_edge_cents * self.quantity,
                event_ticker=ev.event_ticker,
                probability_win=selected.probability_win,
                series_ticker=parsed.ticker.split("-", 1)[0],
                target_date=parsed.target_date,
                target_hour=parsed.target_hour,
                variable=parsed.variable,
                band_lower=parsed.band_lower,
                band_upper=parsed.band_upper,
            )
            if not safety.allowed:
                skipped = f"production_{safety.reason}"

        if skipped == "no_executable_production_liquidity":
            totals["no_liq"] += 1
        elif skipped in ("missing_production_fee_adjusted_edge", "production_insufficient_fee_adjusted_edge"):
            totals["no_edge"] += 1

        snapshot_payload = dict(ev.snapshot)
        snapshot_payload["skipped_reason"] = skipped
        snapshot_id = self.store.insert_shadow_snapshot(scan_id, snapshot_payload)
        totals["snapshots"] += 1

        if skipped is None and selected.ask_cents is not None and selected.fee_cents is not None:
            self.store.insert_shadow_order(scan_id, snapshot_id, {
                "ticker": parsed.ticker,
                "side": selected.side,
                "quantity": self.quantity,
                "limit_price_cents": selected.ask_cents,
                "avg_fill_price_cents": selected.ask_cents,
                "fee_cents": selected.fee_cents,
                "status": "SHADOW_FILLED",
                "reason": "production_liquidity_fee_adjusted_edge",
            })
            totals["fills"] += 1

    def reconcile_settlements(self, limit: int | None = None) -> ShadowReconcileResult:
        checked = settled = 0
        tickers = self.store.unsettled_shadow_order_tickers()
        if limit is not None:
            tickers = tickers[:limit]
        for ticker in tickers:
            market = self.kalshi.get_market(ticker)
            checked += 1
            settled += self.store.settle_shadow_orders_for_market(ticker, market)
        return ShadowReconcileResult(checked, settled)

    def _candidate(self, side: str, ask_cents: float | None, ask_size: float, probability_win: float) -> TradeCandidate:
        fair = probability_win * 100.0
        fee = self.fee_model.buy_fee_cents(ask_cents, self.quantity) if ask_cents is not None else None
        ev = self.fee_model.buy_ev_cents(probability_win, ask_cents, self.quantity) if ask_cents is not None else None
        return TradeCandidate(side, ask_cents, ask_size, probability_win, fair, fee, ev)

    def _forecast_value(self, lat: float, lon: float, parsed) -> float | None:
        if parsed.variable == WeatherVariable.POINT_TEMP_F and parsed.target_hour is not None:
            key = (lat, lon, parsed.target_date, parsed.target_hour)
            if key not in self._hourly_cache:
                self._hourly_cache[key] = self.weather.hourly_temperature(lat, lon, parsed.target_date, parsed.target_hour)
            return self._hourly_cache[key]
        key = (lat, lon, parsed.target_date)
        if key not in self._daily_cache:
            self._daily_cache[key] = self.weather.daily_forecast(lat, lon, parsed.target_date)
        return value_for_variable(self._daily_cache[key] or {}, parsed.variable)

    def _geocode(self, city: str) -> tuple[float, float, str] | None:
        if city not in self._geo_cache:
            self._geo_cache[city] = self.weather.geocode(city)
        return self._geo_cache[city]

    def _rain_probability(self, lat: float, lon: float, parsed) -> float | None:
        """Forecast precipitation probability for an "any rain" market, else None."""
        if parsed.variable != WeatherVariable.RAIN_IN or parsed.threshold is None or parsed.threshold > 0.25:
            return None
        daily = self._daily_cache.get((lat, lon, parsed.target_date))
        if not daily:
            return None
        try:
            return float(daily.get("precipitation_probability_max")) / 100.0
        except (TypeError, ValueError):
            return None

    def _usable(self, parsed) -> bool:
        return bool(
            parsed.city
            and parsed.target_date
            and parsed.threshold is not None
            and parsed.variable != WeatherVariable.UNKNOWN
            and (parsed.variable != WeatherVariable.POINT_TEMP_F or parsed.target_hour is not None)
        )


class _ShadowSafetyView:
    """Adapts the shadow_orders ledger to the read interface SafetyGuard expects (the same
    method names the Store exposes for paper orders), delegating to the Store's shadow_*
    helpers so all SQL/backend dialect lives in storage.py."""

    def __init__(self, store: Store):
        self.store = store

    def count_orders_today(self) -> int:
        return self.store.count_shadow_orders_today()

    def count_orders_since(self, ticker: str, side: str, minutes: int) -> int:
        return self.store.count_shadow_orders_since(ticker, side, minutes)

    def has_opposite_position(self, ticker: str, side: str) -> bool:
        return self.store.shadow_has_opposite_position(ticker, side)

    def position_quantity(self, ticker: str, side: str | None = None) -> int:
        return self.store.shadow_position_quantity(ticker, side)

    def total_open_exposure_cents(self) -> float:
        return self.store.shadow_total_open_exposure_cents()

    def event_order_quantity(self, event_ticker: str) -> int:
        """Contracts already placed on this correlated event, open or settled."""
        return self.store.shadow_event_order_quantity(event_ticker)

    def event_position_quantity(self, event_ticker: str, side: str | None = None) -> int:
        return self.store.shadow_event_position_quantity(event_ticker, side)

    def event_open_exposure_cents(self, event_ticker: str) -> float:
        return self.store.shadow_event_open_exposure_cents(event_ticker)

    def same_day_directional_order_quantity(self, series_ticker: str, target_date: str, side: str) -> int:
        return self.store.shadow_same_day_directional_order_quantity(series_ticker, target_date, side)

    def adjacent_hour_directional_order_quantity(self, series_ticker: str, target_date: str, target_hour: int, side: str, window: int) -> int:
        return self.store.shadow_adjacent_hour_directional_order_quantity(series_ticker, target_date, target_hour, side, window)


def _market_is_tradeable(market: dict) -> bool:
    status = str(market.get("status") or "").lower()
    if status and status not in {"active", "open"}:
        return False
    close_time = market.get("close_time")
    if close_time:
        try:
            close_dt = datetime.fromisoformat(str(close_time).replace("Z", "+00:00"))
            if close_dt <= datetime.now(timezone.utc):
                return False
        except ValueError:
            pass
    return True


def _depth_from_orderbook(payload: dict[str, Any]) -> dict[str, float]:
    book = payload.get("orderbook") or payload.get("results") or payload
    yes_levels = book.get("yes") or []
    no_levels = book.get("no") or []
    best_yes = _best_level(yes_levels)
    best_no = _best_level(no_levels)
    return {
        "yes_ask_size": best_no[1] if best_no else 0.0,
        "no_ask_size": best_yes[1] if best_yes else 0.0,
    }


def _best_level(levels: list[Any]) -> tuple[float, float] | None:
    best: tuple[float, float] | None = None
    for level in levels:
        price, size = _level_price_size(level)
        if price is None:
            continue
        candidate = (price, size or 0.0)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return best


def _level_price_size(level: Any) -> tuple[float | None, float | None]:
    if isinstance(level, dict):
        raw_price = level.get("price") or level.get("yes_price") or level.get("no_price")
        raw_size = level.get("size") or level.get("count") or level.get("quantity")
    elif isinstance(level, (list, tuple)):
        raw_price = level[0] if len(level) >= 1 else None
        raw_size = level[1] if len(level) >= 2 else None
    else:
        raw_price = raw_size = None
    return _optional_float(raw_price), _optional_float(raw_size)


def _spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    return ask - bid


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else 0.0


def _first_float(*values: Any) -> float:
    for value in values:
        parsed = _float_or_zero(value)
        if parsed > 0:
            return parsed
    return 0.0
