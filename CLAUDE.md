# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical safety invariants

This is a **research/demo/shadow-only** Kalshi trading bot. No live (production) orders are ever placed. Preserve these invariants in any change:

- `DemoExecutor` (`demo_execution.py`) refuses to construct unless `KalshiClient.is_demo` is true (base URL contains `demo`). It only submits **fill-or-kill** orders.
- `ProductionShadowTracker` (`shadow.py`) reads the production/external API (`KALSHI_SHADOW_BASE_URL`) but **never submits orders** — it only records snapshots and hypothetical "shadow" fills.
- Demo fills/wins are engineering validation only, not proof of live profitability. Do not add a live-trading path; that is Phase 3 and gated on preconditions in `plan.md` (event-level exposure limits, manual approval, kill switch, read/write key separation).
- Before changing order direction/submission, verify Kalshi API docs. Note the BUY NO mechanic: buying NO at N¢ is implemented as an **ASK on the YES book at (100−N)¢**, since Kalshi binary markets are a single YES book.

For a fresh-agent handoff, read `PROJECT_STATUS.md` first, then `plan.md`.

## Current status (2026-05-28): model was empirically unprofitable; risk-control fixes shipped

Production shadow tracking ran and settled; the first 18 settled shadow fills went **4 wins / 14 losses (-74¢)**. A from-the-data audit (`shadow_orders`⋈`shadow_snapshots`) found the documented "too-tight sigma" story was only part of it. The **entire** -74¢ was one event (hour 19, -155¢); hours 17 and 18 were net *profitable* under the same sigma. The dominant driver was **correlated-ladder over-betting**: within one hourly event all strikes resolve off the same temperature, yet the bot placed up to 6 same-direction bets on it (the per-event cap counted both sides combined and capped per *hour*, not per day), so one wrong forecast → 6 simultaneous losses. Three compounding root causes, in impact order:

- **A — correlated-ladder over-betting (dominant).** Backtest: best-strike-per-event cuts the loss ~10–12× vs all-strikes.
- **B — overconfident `probability._sigma`** (2.5°F at lead 0 vs realized 1.3–3.3°F error + station basis).
- **C — edge gate ignored forecast uncertainty** (point forecast vs 1°-spaced strikes when forecast MAE ≈ spacing).

**Fixes shipped (2026-05-28):** see `PROJECT_STATUS.md` → "risk-control fixes".
1. (A) `BEST_STRIKE_PER_EVENT=true` (default): `paper.py`/`shadow.py` now evaluate every strike but place only the single highest fee-adjusted-EV order per event (two-pass `run_once`; non-best strikes recorded with skip reason `not_best_strike_in_event`).
2. (B) `probability._sigma` widened (lead-0 point-temp 2.5→4.5°F) from realized error.
3. (C) `FORECAST_UNCERTAINTY_GATE_RATIO`: skip temperature markets where `sigma ≥ ratio × strike_spacing` (skip reason `forecast_uncertainty_exceeds_strike_spacing`). The runtime `.env` is back to the conservative `1.0` after the follow-up losses; this skips `KXTEMPNYCH` hourly unless deliberately raised for shadow data collection.

Follow-up fix (2026-05-29): `BEST_STRIKE_PER_EVENT` was only per scan, so repeated scans could still stack different strikes in the same event. Safety now defaults to one order per event across scans (`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT=true`, `MAX_CONTRACTS_PER_EVENT=1`, skip `event_already_traded` / `production_event_already_traded`). The EV selector also favored low-probability 1¢/4¢ tail bets; `MIN_TRADE_PROBABILITY=0.55` now skips those before best-strike selection.

Fresh-lens reset (2026-05-29): all prior runtime data was archived to `data/archive/kalshi_weather_20260529_134719.sqlite` with summary/manifest files, then the live `data/kalshi_weather.sqlite` was cleared in place. The live DB now starts from zero rows; use the archive only for historical comparison, not current calibration.

Remaining model work (still open): forecast bias-correction per station/variable/hour, and re-scoring `kalshi-weather-calib --source shadow` after new post-reset data settles. Do not treat any positive demo, pre-fix, or archived number as evidence of edge.

### ACTIVE EXPERIMENT (2026-05-30 → auto-reverts 2026-06-06): relaxed shadow gate
Post-reset, the conservative gate (`FORECAST_UNCERTAINTY_GATE_RATIO=1.0` vs 1 F spacing, σ≥4.5) blocked **100% of temperature markets** in shadow (94.7% of all shadow evals skipped) — a deadlock, since the model needs settled temperature data to recalibrate σ but the gate records none. Fix: shadow-only `SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO=6.0` + `SHADOW_GATE_EXPERIMENT_UNTIL=2026-06-06`, resolved by `Settings.effective_shadow_gate_ratio()` and used in `shadow.py` `_fails_uncertainty_gate`. **`paper.py`/demo stay at `1.0`; shadow is read-only (no orders).** The gate auto-reverts to `1.0` after the date. All other controls (`MIN_TRADE_PROBABILITY`, EV gate, `BEST_STRIKE_PER_EVENT`, per-event caps) remain in force, so the correlated-ladder failure mode stays blocked. On/after 2026-06-06, run `kalshi-weather-calib --source shadow` over the new fills. Design: `docs/superpowers/specs/2026-05-30-shadow-gate-experiment-design.md`. Fills from this window are calibration data, not edge.

### Ledger layers (clarification for fresh agents)
There are three ledgers and they are **not** interchangeable: `paper` is the decision engine + complete signal record (works without creds; the source of truth for calibration); `demo` is **a hook inside `PaperTrader`** that mirrors paper fills to the Kalshi demo API (plumbing validation only — thin/stale books, not profitability proof); `shadow` reads production prices and is the real go/no-go signal. Removing the paper layer would remove the brain that demo execution depends on.

## Commands

Install (editable) and configure:

```bash
python -m venv .venv
. .venv/Scripts/activate        # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
cp .env.example .env            # then fill in Kalshi credentials
```

Console-script entry points (defined in `pyproject.toml`; each also runnable as `python -m kalshi_weather_bot.<module>`):

| Command | Module | Purpose |
|---|---|---|
| `kalshi-weather-scan` | `cli` | Phase 1 read-only edge scan |
| `kalshi-weather-paper` | `paper_cli` | Phase 2 local paper scan (SQLite ledger) |
| `kalshi-weather-demo` | `demo_cli` | Phase 2.5 demo execution / `--snapshot` |
| `kalshi-weather-shadow` | `shadow_cli` | Phase 2.75 production shadow scan (read-only) |
| `kalshi-weather-pnl` | `pnl_cli` | Reconcile settled markets, update paper P/L |
| `kalshi-weather-calib` | `calibration` | Brier/log-loss/reliability + forecast MAE/bias over settled orders |
| `kalshi-weather-runner` | `runner` | Continuous loop (scan + settle + optional demo/shadow) |
| `kalshi-weather-app` | `app` | Dashboard + background runner in one process |
| `kalshi-weather-web` | `web_ui` | Dashboard only (`http://127.0.0.1:8787`) |

Common invocations:

```bash
kalshi-weather-scan --limit 50
kalshi-weather-demo --limit 50 --execute-demo          # only submits qualifying FOK orders
kalshi-weather-shadow --limit 50 --settle              # production shadow + settlement
kalshi-weather-calib --source shadow                   # is the model calibrated? (go/no-go signal)
kalshi-weather-runner --limit 50 --execute-demo --production-shadow --interval-seconds 900
kalshi-weather-runner ... --once                       # single iteration then exit
python -m kalshi_weather_bot.app --port 8787 --execute-demo --production-shadow --interval-seconds 900
```

Windows `.bat` helpers: `start_demo_bot.bat` (app + demo), `start_dashboard.bat` (web only), `run_week_test.bat` (runner, `--limit 200`).

### Tests / verification

There is no test suite. The repo's verification gate is that the package compiles:

```bash
python -m compileall src
```

`--limit` semantics: when `KALSHI_SERIES_TICKERS` is set (the default), `--limit` / `KALSHI_MARKET_LIMIT` is **per configured series**, not a global total. The scanner filters `/markets` by series ticker rather than grabbing the first N open markets.

## Architecture

Single SQLite file `data/kalshi_weather.sqlite` (WAL mode) is the source of truth for all modes. Schema lives in `storage.py` (`Store`); tables: `scans`, `signals`, `paper_orders`, `paper_positions`, `demo_orders`, `demo_snapshots`, `shadow_snapshots`, `shadow_orders`, plus runner events. New columns are added idempotently in `Store._migrate` (and must also be added to the `insert_signal`/`insert_shadow_snapshot` key lists). Notable added columns: `band_lower`/`band_upper`/`event_ticker`/`lookahead_risk` on signals & snapshots; `result_value` on orders.

### Scan pipeline (`paper.py` `PaperTrader.run_once`)

For each configured series → each market:

1. `_market_is_tradeable` — skip non-`active/open` status or past `close_time`.
2. `market_parser.parse_market` — extract city / variable / target date / target hour, and the strike via `parse_strike_from_ticker`: one-sided `threshold`+`comparator` for `-T##`, or `band_lower`/`band_upper` for `-B##.#` bucket markets. POINT_TEMP_F markets require a target hour.
3. Location + forecast — `stations.station_for_ticker` gives exact settlement coordinates (preferred); else `weather.geocode`. Then Open-Meteo forecast (free/keyless), cached per run. Same-day/elapsed contracts get `lookahead_risk=1` (forecast leaks observed weather).
4. `probability.estimate_probability` — normal model → `P(YES)`. Bands use `P(lo≤X<hi)`; rain "any-rain" markets use a `direct_probability` from `precipitation_probability_max`. `_sigma` was recalibrated wider on 2026-05-28 (lead-0 point-temp 4.5°F); `strike_spacing`/`forecast_resolves_strikes` back the uncertainty gate.
5. `orderbook.parse_orderbook` / `parse_market_quote` — current YES/NO quotes and sizes.
6. Build **BUY_YES** and **BUY_NO** `TradeCandidate`s, compute fee-adjusted EV via `fees.FeeModel`:
   - YES EV = `P(YES)*100 − YES ask − fee`
   - NO EV = `(1−P(YES))*100 − NO ask − fee`
   - Select the higher executable EV candidate (requires `ask_size >= quantity`).
   - **Forecast-uncertainty gate (C):** for temperature markets, skip when `sigma ≥ FORECAST_UNCERTAINTY_GATE_RATIO × strike_spacing` (`forecast_uncertainty_exceeds_strike_spacing`).
6b. **Two-pass `run_once` (A):** all markets are evaluated first (`_evaluate_market`, stateless), then `BEST_STRIKE_PER_EVENT` keeps only the single highest-EV tradeable strike per event (`_mark_best_strike_per_event`; others → `not_best_strike_in_event`), then `_persist_evaluation` writes signals and runs stateful safety on survivors.
7. `safety.SafetyGuard.check` — hard limits (see below). Records a `signal` row always; only inserts a `FILLED` `paper_order` + upserts `paper_position` when not skipped.
8. If a `DemoExecutor` is attached and an order filled, submit the matching FOK demo order. On demo error, the local order is marked `DEMO_REJECTED` (excluded from open exposure).

Skip reasons (recorded on the signal) drive dashboard metrics; `no_executable_liquidity` is expected to be high for thin weather ladders.

### Layers

- `config.py` — `Settings` (pydantic-settings, reads `.env`). Holds series list, base URLs, limits, `min_edge_cents`. `safety.py` has its own `SafetySettings`.
- `kalshi_client.py` — authenticated REST client. Signs `timestamp+method+path` with RSA-PSS/SHA256 (`cryptography`). Has 429 retry/backoff and embeds response body in `HTTPError`. `is_demo` gates execution. Demo `/portfolio/positions` is queried without params (some param combos return 401).
- `safety.py` — `SafetyGuard`: min fee-adjusted EV, minimum selected-side win probability (`MIN_TRADE_PROBABILITY`), side-aware price bounds, max orders/day, per-market cooldown, opposite-side block, max contracts/market, **per-event caps** (`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT`, `MAX_CONTRACTS_PER_EVENT`, `MAX_EVENT_EXPOSURE_CENTS`; `_event_ticker` groups per city/day/**hour**), max total exposure. All from env.
- `probability.py` — normal-CDF fair value. `_sigma(variable, lead_days)` (recalibrated wider 2026-05-28); band + `direct_probability` (rain) branches; clamps to [0.01, 0.99]. Also exposes `strike_spacing` + `forecast_resolves_strikes` for the uncertainty gate. Calibrate `_sigma` further from `kalshi-weather-calib` as data settles.
- `stations.py` — series-prefix → `(lat, lon, source_label)` for exact settlement stations (NYC Central Park, Chicago Midway, …); falls back to geocoding.
- `calibration.py` / `kalshi-weather-calib` — joins settled orders to their predicted probability; computes Brier, log loss, reliability bins, forecast MAE/bias, independent-event counts. Excludes `lookahead_risk` rows by default.
- `demo_execution.py` — demo-only FOK order backend (`buy_yes_fok`, `buy_no_fok`, `snapshot_portfolio`).
- `shadow.py` / `shadow_cli.py` — Phase 2.75: same scan logic against the production read API, writes `shadow_snapshots`/`shadow_orders`, tracks shadow P/L separately. Never posts orders.
- `pnl.py` / `pnl_cli.py` — `reconcile_paper_settlements`: checks unsettled tickers against Kalshi results, writes payout/realized P/L back to `paper_orders`.
- `runner.py` — loops: `PaperTrader.run_once` → `reconcile_paper_settlements` → optional `ProductionShadowTracker`. Logs each iteration as a runner event.
- `app.py` — runs `web_ui` dashboard + background runner together.
- `web_ui.py` — stdlib HTTP dashboard reading the SQLite store (scan counts, side mix, skip reasons, orders, shadow snapshots/fills, realized P/L, open exposure, win rate).

## Configuration & secrets

All runtime config is env-driven via `.env` (see `.env.example`). Auth requires `KALSHI_API_KEY_ID` plus **either** `KALSHI_PRIVATE_KEY_PATH` (preferred — points to a PEM file) **or** `KALSHI_PRIVATE_KEY` (single quoted line with escaped `\n`). `KALSHI_BASE_URL` defaults to the demo API; `KALSHI_SHADOW_BASE_URL` to the external/production read API.

Shadow tracking needs **real production read credentials** — `KALSHI_SHADOW_API_KEY_ID` + `KALSHI_SHADOW_PRIVATE_KEY_PATH` (or `KALSHI_SHADOW_PRIVATE_KEY`), which `shadow.py` overrides into a production `Settings` copy. They fall back to the primary keys, but the production API rejects demo keys, so without real production creds `shadow_snapshots` stays empty. Safety/event caps: `MAX_CONTRACTS_PER_EVENT`, `MAX_EVENT_EXPOSURE_CENTS`.

`.env`, `data/`, `*.sqlite`, and the `.pem`/`.txt.bak` key files are gitignored (not all are removed from disk). Never commit credentials or the private key.
