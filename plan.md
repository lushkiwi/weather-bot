# Kalshi Weather Trading Bot Plan

> Fresh-agent note: also read `PROJECT_STATUS.md`. It contains the current implementation status, verified commands, BUY YES/BUY NO notes, and next tasks.

> **Status (2026-05-29): shadow tracking exposed losses; risk controls were tightened again; prior data archived.** A from-the-data audit found the dominant driver was **correlated-ladder over-betting** (the first -74¢ was one event where the bot stacked 6 same-direction bets), not just the too-tight `probability._sigma`. Shipped: `BEST_STRIKE_PER_EVENT`, a wider recalibrated `_sigma`, a conservative `FORECAST_UNCERTAINTY_GATE_RATIO=1.0`, across-scan event lockout, and `MIN_TRADE_PROBABILITY=0.55`. Previous trades/results were archived to `data/archive/kalshi_weather_20260529_134719.sqlite`, and the live DB was reset for fresh post-fix evaluation. Still open: forecast bias-correction + re-calibration after more post-reset days. See `PROJECT_STATUS.md`.

> **Infra (2026-06-02): now cloud-hosted.** Migrated off self-hosted Windows to **Railway** (cron `runner` every 10 min + always-on `dashboard`) backed by **Supabase Postgres**, code on GitHub. The cron runs `--shadow-only` (read-only production shadow; no demo orders, **no live trading** — Phase 3 below is still gated). `Store` is dual-backend (Postgres via `DATABASE_URL`, else local SQLite). See `docs/deployment.md` and `PROJECT_STATUS.md`.

## Goal
Build a weather-market edge scanner and trading system for Kalshi. Phase 1 is read-only: discover open weather markets, estimate fair probabilities from external weather forecasts, compare against Kalshi orderbook prices, and rank potential edges. No orders are placed in Phase 1.

Current near-term goal: keep the demo bot/dashboard running while collecting **production-market shadow tracking** data. Demo fills are useful for validating execution plumbing, but demo liquidity/prices are not the same as live Kalshi markets. Before any live trading, the bot should record real production orderbooks and evaluate whether the algorithm would have found executable edges in the real market over several days.

## Strategy Recommendation
Use a hybrid system:

1. **Quantitative model as the decision engine**
   - Ingest market data and weather forecasts.
   - Produce calibrated probabilities.
   - Compare probabilities to market prices after fees/spread/liquidity.
   - Enforce deterministic risk controls.

2. **LLM as analyst/research assistant**
   - Explain why a signal exists.
   - Summarize model/source disagreement.
   - Flag ambiguous settlement rules.
   - Generate reports.
   - Do not let the LLM directly place trades.

## Phase 1 — Read-only scanner

### Deliverables
- Project scaffold.
- Kalshi authenticated read-only client.
- Weather-market discovery.
- Heuristic market parsing for city/variable/threshold/date.
- Free weather forecast ingestion via Open-Meteo.
- Simple probability estimator.
- Edge ranking report.
- CLI entry point.

### Non-goals
- No live trading.
- No order placement.
- No automated position sizing.
- No claim of profitability before backtesting/paper validation.

### Required user-provided secrets/services
- `KALSHI_API_KEY_ID` — Kalshi API key id.
- One of:
  - `KALSHI_PRIVATE_KEY_PATH` — path to RSA private key file, or
  - `KALSHI_PRIVATE_KEY` — private key contents.
- Optional:
  - `KALSHI_BASE_URL` — defaults to Kalshi demo/paper URL.
  - `OPENAI_API_KEY` — later for LLM analyst reports, not needed for Phase 1 core scanner.

## Phase 2 — Paper trader

### Deliverables
- Local prediction ledger in `data/kalshi_weather.sqlite`.
- Simulated order placement/fills from orderbook/market quote snapshots.
- Fee-adjusted EV model.
- Paper position tracking.
- Calibration metrics: Brier score, log loss, realized ROI, slippage.
- Signal persistence for later backtesting.

### Why local paper storage even with Kalshi demo?
Kalshi demo can track positions only if the bot submits demo orders. Phase 2 should remain safe and research-first: it records every signal, every skip reason, the exact forecast snapshot, quote, fee-adjusted EV, and hypothetical fill. Demo positions can be added later as an execution backend, but local storage remains the source of truth for model evaluation and backtesting.

### Inputs from Phase 1
- Market ticker.
- Parsed contract metadata.
- Forecast snapshot.
- Estimated probability.
- Best bid/ask.
- Expected value.
- Skip/trade recommendation.

## Phase 2.5 — Kalshi demo execution backend

### Deliverables
- Optional demo-only order execution.
- Continuous runner for unattended scans.
- Dashboard graphs for signal volume and skip mix.
- Refuse non-demo API base URLs.
- Fill-or-kill BUY YES orders only.
- Local SQLite remains the research source of truth.
- Store demo order ids, responses, errors, balance snapshots, and position snapshots.
- Reconcile local paper fills vs Kalshi demo fills.
- Hard safety limits: max orders/day, max contracts/market, max exposure, and side-aware price bounds.
- BUY YES and BUY NO candidate evaluation.

### Commands
- `python -m kalshi_weather_bot.demo_cli --snapshot`
- `python -m kalshi_weather_bot.demo_cli --limit 200 --execute-demo`

## Phase 2.75 — Production-market shadow tracking

### Why this phase is required
Kalshi demo is not a reliable proxy for live profitability. Demo markets can be thin, stale, artificially quoted, or otherwise different from production markets. The current demo win rate should be treated as engineering validation, not proof of real-world edge.

### Deliverables
- [x] Read production/external Kalshi market data without submitting production orders.
- [x] Keep demo execution optional and separate from production shadow data.
- [x] Store production orderbook snapshots for the configured weather series.
- [x] Evaluate hypothetical fills only when production orderbook liquidity is executable at the recorded ask.
- [x] Track shadow P/L, win rate, edge, spreads, and available size.
- [x] Dashboard demo-vs-production overlap report (matched by ticker) + "Model calibration" tile.
- [x] Dashboard/reporting for recent production shadow snapshots/fills and headline P/L.
- [x] Calibration tooling (`kalshi-weather-calib`): Brier, log loss, reliability, forecast MAE/bias.
- [x] Per-event exposure caps for correlated ladders (`safety.py`).
- [x] Preserve strict no-live-trading default.

### Empirical finding (the current blocker)
Shadow data shows **no edge** on the most-traded markets (`KXTEMPNYCH` hourly): the forecast MAE (~2°F) is ≥ the strike spacing, so the model is trading noise into a spread, and the tight `sigma` amplifies it into real losses. This must be fixed before continuing — see Phase 4, which is now the active phase, not a future one.

### Cadence recommendation
- Start with 15-minute scans for broad production shadow tracking.
- Add faster 3–5 minute scans for near-close hourly temperature markets if API usage is stable.
- Do not use 1–2 minute near-close scans until rate limits, duplicate-order prevention, and event-level exposure controls are solid.

## Phase 3 — Controlled live trading

### Preconditions
- Several days of production-market shadow tracking.
- **Calibrated probabilities** (`kalshi-weather-calib` showing Brier well below 0.25 and reliability close to the diagonal) — currently FAILING.
- **Positive, fee-aware shadow P/L on non-leakage fills** — currently NEGATIVE (-74¢ over first 18).
- Evidence that edges are executable in production, not just demo.
- Event-level exposure limits for correlated temperature ladders (done).
- Manual approval reviewed and tested.

### Deliverables
- Manual-approval mode.
- Tiny sizing only.
- Limit orders only.
- Kill switch.
- Max exposure per market/event/day.
- Max daily loss.
- Read/write key separation.

## Phase 4 — Better forecasting model (NOW THE ACTIVE PHASE)

The shadow results promoted this from "future" to "blocking." Concrete near-term tasks, in order:
1. ✅ **Done (2026-05-28): calibrate/widen `probability._sigma`** from realized forecast error (lead-0 point-temp 2.5→4.5°F, high/low 3→5°F). Re-tune from `kalshi-weather-calib` as more data settles.
2. **Forecast bias correction** per station/variable/hour using the stored `forecast_value` vs `result_value` history (extend `stations.py` + a rolling-error table). **(still open)**
3. ✅ **Done (2026-05-28): edge gate that accounts for forecast uncertainty** — `FORECAST_UNCERTAINTY_GATE_RATIO` skips markets where `sigma ≥ ratio × strike_spacing` (`probability.forecast_resolves_strikes`).
4. ✅ **Done (2026-05-28): correlated-ladder fix** — `BEST_STRIKE_PER_EVENT` places only the single best-EV strike per event per scan (this was the dominant loss driver, ahead of sigma).
5. ✅ **Done (2026-05-29): across-scan event lockout + probability floor** — repeated scans can no longer add more strikes to an already-traded event (`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT=true`, `MAX_CONTRACTS_PER_EVENT=1`), and low-probability tail bets are skipped by `MIN_TRADE_PROBABILITY=0.55`.

### Later deliverables
- Station/city mapping improvements (`stations.py` started).
- Historical data warehouse.
- Forecast-model blending: NWS, HRRR, GFS, NAM, ECMWF if available.
- Bias correction by station, variable, lead time, and season.
- Backtested thresholds and sizing rules.

## Suggested stack

- Python 3.11+
- `requests` for APIs
- `cryptography` for Kalshi RSA-PSS signing
- `python-dotenv` for local env loading
- `pydantic` for typed settings/models
- Later: PostgreSQL/TimescaleDB, DuckDB/Parquet, Streamlit, OpenAI API

## Current implementation notes

The initial implementation is intentionally conservative:
- It only reads market/orderbook data.
- It uses Open-Meteo because it is free and keyless.
- Probability estimates are baseline approximations, not production-grade forecasts.
- Any edge report must be treated as research until validated with paper trading.

## Handoff instructions for new Pi instances

1. Read this `plan.md`.
2. Inspect `README.md` and `src/kalshi_weather_bot/`.
3. Confirm Phase 1 scanner runs with valid Kalshi credentials.
4. For Phase 2, add persistence under `data/` and implement paper-fill simulation.
5. Do not enable live trading until Phase 3 risk controls exist and have been reviewed.
