# Kalshi Weather Bot Project Status

## Current objective
Build a Kalshi weather-market bot that can scan weather contracts, estimate fair probabilities, paper trade locally, optionally submit qualifying orders to Kalshi demo, and show results in a local web dashboard.

Near-term objective: keep **production-market shadow tracking** running as a read-only data-collection and model-debugging loop. Current post-reset shadow evidence is negative, so the goal is no longer to validate an apparent edge; it is to diagnose forecast/model failures before any Phase 3/live-trading consideration.

## Current phase
Implemented phases:
- Phase 1: read-only scanner.
- Phase 2: local paper-trading ledger.
- Phase 2.5: optional Kalshi demo execution backend, continuous runner, dashboard graphs, settlement reconciliation, and safety limits.
- Phase 2.75: production-market shadow tracking.

Current cloud mode is **Phase 2.75 shadow-only** on Railway/Supabase: production prices are read, shadow fills are simulated, and no demo/live orders are placed.

## 2026-06-02 cloud migration (now hosted on Railway + Supabase)
The bot no longer runs self-hosted on Windows. It is deployed to the cloud:
- **Supabase Postgres** (project `weather-bot`, ref `xtttchcsmlzjsxcnrttb`) is the hosted database;
  `storage.py` `Store` is now **dual-backend** (Postgres when `DATABASE_URL` is set, SQLite locally).
- **Railway** runs two services from GitHub `lushkiwi/weather-bot`: a cron **`runner`**
  (`*/10 * * * *`, `python -m kalshi_weather_bot.runner --once --production-shadow --shadow-only --limit 50`)
  and an always-on **`dashboard`** (public `*.up.railway.app` URL, reads Supabase).
- New `runner --shadow-only` flag runs only the read-only production shadow scan (no demo client),
  so the cron needs only production read creds. **No live trading; no demo orders in the cloud.**
- Build uses a root **`Dockerfile`** with `dockerfilePath` set per service (Railway's Railpack/Nixpacks
  builders don't install this src-layout package). Deploys are triggered via the Railway GraphQL API
  (auto-deploy-on-push not yet wired). Verified end-to-end: a cron run scanned 169 live markets and
  wrote 37 shadow snapshots / 3 shadow fills to Supabase; the dashboard renders them.

Full details, service IDs, and env vars: `docs/deployment.md`. The model-quality status and all
trading caveats below are unchanged by the migration.

## 2026-06-08 shadow performance update — still losing, now with clean negative evidence
A live Supabase review of the post-reset production-shadow ledger (`observations.md`, generated 2026-06-08 00:51 UTC) found:
- **83 total shadow fills:** 79 settled, 4 open; all are simulated/read-only production-shadow fills.
- **Settled P/L: −469¢** on 2,169¢ cost basis (**−21.6% ROI**), **17/79 wins (21.5%)**.
- Model calibration is poor: mean side-aware predicted win probability **69.3%** vs 21.5% empirical; Brier **0.386**, log loss **0.991**.
- First clean/non-lookahead rows have settled: **7 fills, −172¢**, mean predicted win probability **90.7%**. The first go/no-go-quality sample is negative.
- By series: `KXTEMPNYCH` −245¢ (forecast MAE 3.22°F vs 1°F strikes), `KXHIGHCHI` −177¢, `KXRAINNYC` −47¢.
- Safety regressions remain fixed: no `event_ticker` has multiple shadow orders, and no filled order has side-aware `p_win < 0.55`.
- New/remaining failure modes: adjacent-hour same-direction temp losses, overconfident probabilities, Open-Meteo/settlement-source bias, expensive BUY_NO payoff asymmetry, and band/rain model calibration errors.
- Operational issue to monitor: one stale past-close shadow fill (`shadow_orders.id=79`, `KXTEMPNYCH-26JUN0521-T79.99`) remained unsettled during the report.

Conclusion: **do not live trade**. Treat the bot as a shadow data collector/model debugging tool until bias correction, σ/band/rain recalibration, adjacent-hour risk caps, and skipped-trade counterfactual audits are implemented and re-tested.

## 2026-05-28 algorithm audit fixes (Findings 0–5)
A code/data audit (see `~/.claude/plans/analyze-the-algorithm-and-golden-sutherland.md`) found and fixed:
- **F0 shadow was recording nothing.** `start_demo_bot.bat` now passes `--production-shadow`. Production shadow reads now use dedicated, optional credentials (`KALSHI_SHADOW_API_KEY_ID` / `KALSHI_SHADOW_PRIVATE_KEY_PATH` / `KALSHI_SHADOW_PRIVATE_KEY`, falling back to the primary keys) — the external production API rejects demo keys. **Set these to a real production read key or shadow stays empty.**
- **F6 per-market error isolation.** `paper.py`/`shadow.py` `run_once` now isolate each market in try/except (`market_errors` counter, logged as runner events) so one failure no longer kills the scan.
- **F1 band-bucket pricing bug.** `-B##.#` bucket markets ("66–67°") were priced as one-sided `P(X≥lower)`. Now `market_parser.parse_strike_from_ticker` reads the strike from the ticker, and `probability.estimate_probability` computes `P(lo≤X<hi)` for bands (continuity-corrected). Verified: Chicago 5/28 B66.5 went 0.617 → 0.261.
- **F2 calibration.** New `calibration.py` + `kalshi-weather-calib` CLI (Brier, log loss, reliability bins, forecast MAE/bias; excludes leakage rows by default) + dashboard "Model calibration" tile. Settlement now stores `result_value`.
- **F3 station mapping.** New `stations.py` maps series prefixes to exact settlement coordinates (NYC Central Park, Chicago Midway); used in preference to city geocoding.
- **F4 rain + leakage.** Rain "any-rain" markets use Open-Meteo `precipitation_probability_max` instead of a Gaussian on the amount; same-day/elapsed contracts carry `lookahead_risk=1`.
- **F5 event controls.** `event_ticker` grouping; new `MAX_CONTRACTS_PER_EVENT` / `MAX_EVENT_EXPOSURE_CENTS` safety caps; calibration reports independent-event counts.

Verification gate (`python -m compileall src`) passes; all modules import; new schema columns migrate idempotently via `Store._migrate`. Calibration on the pre-fix history already shows model overconfidence (predicted 94% vs 82% actual), consistent with F1.

## 2026-05-28 live shadow results — the model is LOSING (root cause diagnosed)
Production shadow tracking is now running and settling. First **18 settled shadow fills: 4 wins / 14 losses, total -74¢.** All were NYC Central Park hourly temperature ladders (`KXTEMPNYCH`) for 5/28 hours 17/18/19.

Root cause (from `shadow_orders` joined to `shadow_snapshots`, not speculation):
- **Forecast error vs the settlement source dominates.** Open-Meteo missed the actual AccuWeather Central Park value by 1–3°F. The 5pm/6pm forecast (~71.3–71.7°) ran high vs realized ~70°; the 7pm forecast (66.7°) ran ~3° LOW vs realized ~70°.
- **The overconfident `sigma` converted forecast error into large losses.** Because `sigma` is tight, the model assigned high conviction (high `p_win`, high prices) and sized into the wrong side. The 7pm NO ladder lost on every strike, including the high-conviction ones: `T69.99` NO @76¢ → **-78¢**, `T68.99` NO @44¢ → **-46¢**.
- This is exactly Findings **F2 (uncalibrated probabilities)** and **F3 (forecast source ≠ settlement source)** showing up empirically. The hourly point-temp forecast MAE (~2°F) is comparable to or larger than the strike spacing, so the model has **no real edge** on those ladders — it is effectively trading noise into a spread.

### Next task: fix the algorithm (forecast quality + calibration), NOT execution
Priority order for a new session:
1. **Widen / calibrate `sigma` in `probability._sigma`.** Current hourly-temp `sigma` (≈2.5–3°F) is too tight given observed ~2°F+ forecast MAE *plus* settlement-source basis. Set it from the realized forecast errors now stored in `result_value` (run `kalshi-weather-calib` to read them). A wider sigma collapses the fake high-conviction edges.
2. **Add forecast bias correction** per (series/station, variable, hour) using the stored `forecast_value` vs `result_value` history (`stations.py` + a rolling-error table).
3. **Stop trading markets where forecast MAE ≥ strike spacing** (esp. `KXTEMPNYCH` hourly) until calibration justifies it — i.e. an EV/edge gate that accounts for forecast uncertainty, not just quote vs point-forecast.
4. Re-run shadow for several more days and re-check `kalshi-weather-calib --source shadow` before any Phase 3 consideration.

Note: a known data quirk — `result_value` sometimes reads a shared field (e.g. all three hours showed 70.0); the per-strike YES/NO `settlement_result` and realized P/L are correct, but treat `result_value` as approximate until verified against the settlement JSON.

## 2026-05-28 risk-control fixes (re-diagnosed from the data, then shipped)
A fresh audit straight from `shadow_orders`⋈`shadow_snapshots` refined the earlier "too-tight sigma" conclusion. Decomposing the -74¢ by event:

| target_hour | forecast | actual | n | wins | P/L |
|---|---|---|---|---|---|
| 17 (5pm) | 71.7° | ~70° | 6 | 2 | **+38¢** |
| 18 (6pm) | 71.3° | ~70° | 6 | 2 | **+43¢** |
| 19 (7pm) | 66.7° | ~70° | 6 | 0 | **−155¢** |

The **entire** loss is hour 19. Hours 17/18 were net profitable under the *same* tight sigma and similar forecast error. The catastrophe on hour 19: the bot placed **6 perfectly-correlated NO contracts** on one event (all betting temp ≪ 70), so one 3.3° forecast miss lost on every strike at once — including a high-conviction NO @76¢ (−78¢). The scans ran ~45–60 min before each hour in ET (UTC `created_at` − 4h), so these were genuine forecasts, not lookahead leakage.

Root causes, in impact order, and the fixes shipped:
- **A — correlated-ladder over-betting (dominant).** `_event_ticker` groups per city/day/**hour** and `MAX_CONTRACTS_PER_EVENT` sums both sides, so 6 same-direction correlated bets were allowed. **Fix:** `BEST_STRIKE_PER_EVENT=true` (new `Settings`, default on) — `paper.py`/`shadow.py` `run_once` is now two-pass: evaluate every strike (`_evaluate_market`), keep only the single highest fee-adjusted-EV tradeable strike per event (`_mark_best_strike_per_event`, others → `not_best_strike_in_event`), then persist + stateful safety (`_persist_evaluation`).
- **B — overconfident sigma.** **Fix:** `probability._sigma` widened from realized error (lead-0 point-temp 2.5→4.5°F; high/low 3→5°F; rain wider).
- **C — edge gate ignored forecast uncertainty.** **Fix:** `FORECAST_UNCERTAINTY_GATE_RATIO` (default 1.0) + `probability.strike_spacing`/`forecast_resolves_strikes`: skip temperature markets where `sigma ≥ ratio × strike_spacing` (skip reason `forecast_uncertainty_exceeds_strike_spacing`).

Verification (`python -m compileall src` passes). Replay over the 18 settled outcomes using the real updated modules:
- Shipped defaults (gate 1.0, best-strike on): the gate skips all `KXTEMPNYCH` hourly (σ 4.5 ≥ 1.0×1.0 spacing) → **0 trades, 0 loss** vs −74¢. This is the honest "no edge on hourly NYC temp" result; raise `FORECAST_UNCERTAINTY_GATE_RATIO` to keep filling for data.
- Isolating fixes (gate relaxed): wider sigma alone = −323¢ (16 tr); wider sigma **+ best-strike-per-event = −27¢ (3 tr)** — best-strike-per-event is the ~10–12× lever.

**Operating decision updated (2026-05-29): runtime `.env` is back to `FORECAST_UNCERTAINTY_GATE_RATIO=1.0`.** The prior `6.0` setting kept hourly/same-day ladders trading for data collection, but follow-up losses showed that was too permissive while the model is uncalibrated. Raise it only deliberately for a bounded shadow-data experiment.

### Ledger layers (do not conflate)
`paper` = the decision engine + the complete signal/skip record (runs without creds; source of truth for `kalshi-weather-calib`). `demo` = a hook *inside* `PaperTrader` that mirrors paper fills to the Kalshi demo API — plumbing validation only (thin/stale books, **not** profitability proof). `shadow` = production prices, the real profitability signal. Demo execution has no decision logic of its own; it depends entirely on the paper trader.

Still open (model quality, unchanged priority): forecast bias-correction per station/variable/hour; re-score `kalshi-weather-calib --source shadow` after more days before any Phase 3 consideration.

## 2026-05-29 follow-up algorithm diagnosis/fixes
A follow-up audit showed the low win rate was not only from old pre-fix orders:
- `BEST_STRIKE_PER_EVENT` only picked one strike **per scan**. Repeated 15-minute scans could still add new strikes in the same event before settlement. Example: `KXTEMPNYCH-26MAY2914` accumulated three losing shadow fills across separate scans.
- The EV selector liked very cheap tail bets (1¢/4¢) with model probabilities below or near 50%. Those can be positive-EV on paper but produce a low win rate and are extremely sensitive to forecast/station error.

Fixes shipped:
- `DISALLOW_MULTIPLE_POSITIONS_PER_EVENT=true` (default): safety now rejects an event once any paper/shadow order has already been placed on that event, open or settled (`event_already_traded` / `production_event_already_traded`).
- `MAX_CONTRACTS_PER_EVENT` default changed from `6` to `1` in code/template.
- Daily order count and cooldown now count settled orders too, not only currently-open rows.
- `MIN_TRADE_PROBABILITY=0.55` (default): candidates below the selected side's model win probability are skipped before best-strike selection (`probability_below_min_trade_probability`), so one low-probability longshot does not crowd out a more plausible strike in the same event.

This is still a research/shadow bot. These changes reduce repeated correlated bets and low-confidence tail bets; they do not prove forecast edge.

## 2026-05-29 archive/reset for fresh evaluation
All previous trades/results were archived before restarting evaluation with a clean live ledger:
- Archive DB: `data/archive/kalshi_weather_20260529_134719.sqlite`
- Manifest: `data/archive/kalshi_weather_20260529_134719_manifest.json`
- Summary: `data/archive/kalshi_weather_20260529_134719_summary.md`
- Archived counts: 218 scans, 5,838 signals, 104 paper orders, 103 demo orders, 1,520 shadow snapshots, 53 shadow orders.
- Archived settled P/L: paper `+2029¢` over 73 settled orders; shadow `-165¢` over 42 settled orders.

The live `data/kalshi_weather.sqlite` was then cleared in place because another process held the DB file open. Current live counts were verified at zero for scans/signals/orders/snapshots/runner events. New calibration and win-rate analysis should use only post-reset rows unless explicitly comparing against the archive.

## 2026-05-30 shadow-gate experiment — ended/reverted after 2026-06-06
A from-the-data review found the post-reset bot is effectively idle on its core strategy: over ~24h, **94.7% of all production-shadow evaluations were skipped by the single `forecast_uncertainty_exceeds_strike_spacing` gate**, and **100% of both temperature series** (`KXTEMPNYCH` hourly, `KXHIGHCHI` daily high) were blocked. With `FORECAST_UNCERTAINTY_GATE_RATIO=1.0`, `DEFAULT_STRIKE_SPACING_F=1.0`, and the widened `_sigma` (≥4.5 F), the pass condition `sigma < 1.0` is unsatisfiable for every 1 F temperature ladder — so the gate is a categorical kill-switch, not a discriminating filter. Only rain markets trade (they bypass the gate via the `direct_probability` path). This is a **deadlock**: the stated near-term goal is to gather shadow data to recalibrate `_sigma`, but the gate prevents recording any settled temperature outcome.

**Fix shipped (shadow-only, bounded, auto-reverting):**
- New `Settings.shadow_forecast_uncertainty_gate_ratio` (`SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO`, default `6.0`) and `Settings.shadow_gate_experiment_until` (`SHADOW_GATE_EXPERIMENT_UNTIL`, default `2026-06-06`), resolved by `Settings.effective_shadow_gate_ratio()`.
- `shadow.py` `_fails_uncertainty_gate` now uses `effective_shadow_gate_ratio()`; **`paper.py`/demo are unchanged and stay at the conservative `1.0`.** Shadow is read-only and never submits orders, so no money/demo path is affected.
- The relaxed ratio applies **only while `date.today() <= 2026-06-06`**, then auto-reverts to the base `1.0`. A forgotten relaxed gate cannot persist.
- **Not relaxed:** `MIN_TRADE_PROBABILITY=0.55`, the EV gate, `BEST_STRIKE_PER_EVENT`, `DISALLOW_MULTIPLE_POSITIONS_PER_EVENT`, `MAX_CONTRACTS_PER_EVENT=1`, cooldown. Even relaxed, only one best strike per event reaches shadow and it must still clear EV + 0.55 conviction, so the −74¢ correlated-ladder failure mode stays blocked.

Design doc: `docs/superpowers/specs/2026-05-30-shadow-gate-experiment-design.md`. **On/after 2026-06-06** the gate reverts automatically unless Railway env vars are deliberately extended. The 2026-06-08 review shows the collected fills were negative and poorly calibrated, including the first clean non-lookahead sample; do not extend relaxed temperature shadow trading as-is. Any future relaxation should be explicitly bounded, read-only, and labeled as calibration data, not edge evidence.

## Important conclusion from recent testing
Kalshi demo is not the same as production. Demo fills/wins validate bot plumbing and can reveal bugs, but they are not proof of live profitability. Demo markets can be thin, stale, or quoted differently from real markets. Before live trading, we need several days of real production market-data shadow results.

## Important files

### Planning/docs
- `plan.md` — phased implementation plan, now including production shadow tracking before live trading.
- `README.md` — setup, run commands, dashboard, runner, demo execution, and production-shadow notes.
- `PROJECT_STATUS.md` — current status for fresh agents.

### Config/secrets
- `.env` — local credentials and runtime config. Gitignored.
- `.env.example` — safe template.
- `kalshi-weather-bot.pem` — local Kalshi private key file. Keep private.

### Runtime data
- `data/kalshi_weather.sqlite` — SQLite source of truth for scans, signals, paper orders, demo orders, snapshots, runner events.

### Main code
- `src/kalshi_weather_bot/config.py` — env config, including `KALSHI_SERIES_TICKERS` and per-series market limit.
- `src/kalshi_weather_bot/kalshi_client.py` — authenticated Kalshi REST client, now supports `series_ticker` filtering and includes 429 retry/backoff plus response-body logging for HTTP errors.
- `src/kalshi_weather_bot/market_parser.py` — parses weather markets; `parse_strike_from_ticker` extracts `-T` (one-sided) and `-B` (band) strikes from the ticker, plus band edges from the title.
- `src/kalshi_weather_bot/weather.py` — Open-Meteo geocoding, daily forecast (incl. `precipitation_probability_max`), hourly temperature.
- `src/kalshi_weather_bot/probability.py` — normal-distribution model; supports band buckets `P(lo≤X<hi)` and a `direct_probability` override for rain. **`_sigma` is hardcoded and currently too tight — this is the main thing to fix (see live results above).**
- `src/kalshi_weather_bot/stations.py` — series-prefix → exact settlement-station (lat, lon, source) mapping; preferred over city geocoding.
- `src/kalshi_weather_bot/calibration.py` / `kalshi-weather-calib` — Brier/log-loss/reliability + forecast MAE/bias over settled paper/shadow orders.
- `src/kalshi_weather_bot/orderbook.py` — parses orderbook/market quotes.
- `src/kalshi_weather_bot/fees.py` — approximate Kalshi fee model.
- `src/kalshi_weather_bot/safety.py` — hard safety limits, including per-event caps (`MAX_CONTRACTS_PER_EVENT`, `MAX_EVENT_EXPOSURE_CENTS`).
- `src/kalshi_weather_bot/storage.py` — SQLite schema and persistence helpers; open exposure now excludes demo-rejected local orders; production shadow tables are `shadow_snapshots` and `shadow_orders`.
- `src/kalshi_weather_bot/paper.py` — local paper trader and optional demo execution hook; filters non-tradeable/closed markets.
- `src/kalshi_weather_bot/demo_execution.py` — demo-only Kalshi execution backend.
- `src/kalshi_weather_bot/shadow.py` / `shadow_cli.py` — Phase 2.75 production-market shadow tracker; read-only against production/external API, records snapshots and shadow fills.
- `src/kalshi_weather_bot/runner.py` — continuous runner, optionally with `--production-shadow`.
- `src/kalshi_weather_bot/app.py` — all-in-one dashboard plus automatic runner.
- `src/kalshi_weather_bot/web_ui.py` — local web dashboard.

## Targeted scanner behavior
The bot no longer scans the first 200 open Kalshi markets. It now filters `/markets` by configured weather series tickers.

Relevant config:
```env
KALSHI_MARKET_LIMIT=50
KALSHI_SERIES_TICKERS=KXTEMPNYCH,KXTEMPCHIH,KXTEMPBOSH,KXTEMPDCH,KXTEMPLAXH,KXTEMPMIAH,KXHIGHAUS,KXHIGHCHI,KXHIGHDEN,KXHIGHHOU,KXPHILHIGH,KXHIGHTSEA,KXHIGHTSFO,KXHIGHNY,KXHIGHMIA,KXLOWTAUS,KXLOWTCHI,KXLOWTBOS,KXLOWNYC,KXLOWLAX,KXRAINAUSM,KXRAINCHIM,KXRAINDALM,KXRAINHOUM,KXRAINLAXM,KXRAINMIAM,KXRAINNYC
```

`KALSHI_MARKET_LIMIT` means markets **per configured series**, not total markets.

## Commands

### Scanner
```bash
kalshi-weather-scan --limit 50
```

### Local paper scan
```bash
kalshi-weather-paper --limit 50
```

### Demo account snapshot
```bash
kalshi-weather-demo --snapshot
```

### Demo execution, only submits qualifying demo FOK orders
```bash
kalshi-weather-demo --limit 50 --execute-demo
```

### All-in-one automatic demo bot + dashboard
```bash
python -m kalshi_weather_bot.app --port 8787 --execute-demo --interval-seconds 900
```
Or:
```bash
start_demo_bot.bat
```

`start_demo_bot.bat` currently runs the app without a hardcoded `--limit`, so the bot uses `.env` defaults.

### Production shadow scan, no live orders
```bash
kalshi-weather-shadow --limit 50 --settle
```

### Continuous runner only
```bash
kalshi-weather-runner --limit 50 --execute-demo --production-shadow --interval-seconds 900
```

### Dashboard only
```bash
kalshi-weather-web --port 8787
```
Open `http://127.0.0.1:8787`.

## Current verified behavior
- Package compiles with `python -m compileall src`.
- Dashboard and demo bot run from `start_demo_bot.bat`.
- The runner scans targeted weather series rather than unrelated markets.
- The scanner includes NYC plus additional cities/series such as Chicago, Austin, Boston, DC, LA, Miami, Denver, Houston, Philadelphia, Seattle, San Francisco, Dallas rain, etc.
- Geocode/weather forecast caching is in place per run to reduce repeated Open-Meteo calls across ladder contracts.
- Markets whose status is not `active/open` or whose close time has passed are skipped before paper/demo execution.
- Demo 409 errors now log response body details going forward.
- If demo execution rejects an order, the corresponding local paper order is marked `DEMO_REJECTED` and excluded from open exposure.

## Recent runtime observations
- Demo execution produced successful demo orders and also a batch of `409 Conflict` errors when attempting to submit some near-close/stale markets.
- One later order submitted successfully: `KXTEMPNYCH-26MAY2719-T73.99 BUY_YES @ 0.5900`.
- A batch of demo-rejected local paper orders was corrected so dashboard open exposure no longer counts them.
- Corrected open exposure after cleanup was approximately `$8.98` across 13 open local/demo-filled positions.
- Local `.env` was temporarily raised to `MAX_ORDERS_PER_DAY=100` for demo-only testing. `.env.example` remains more conservative.

## Current safety limits
Configured in `.env` / `.env.example`:
```env
MAX_ORDERS_PER_DAY=20        # .env may be temporarily higher for demo-only experiments
MAX_CONTRACTS_PER_MARKET=3
MAX_CONTRACTS_PER_EVENT=1     # event = one city/day/hour strike ladder (correlated risk)
DISALLOW_MULTIPLE_POSITIONS_PER_EVENT=true
MAX_EVENT_EXPOSURE_CENTS=1500
MAX_TOTAL_EXPOSURE_CENTS=5000
ORDER_COOLDOWN_MINUTES=240
DISALLOW_OPPOSITE_SIDE_SAME_MARKET=true
MIN_TRADE_PROBABILITY=0.55
MIN_YES_ASK_CENTS=1
MAX_YES_ASK_CENTS=97
MIN_NO_ASK_CENTS=1
MAX_NO_ASK_CENTS=97
# MIN_FEE_ADJUSTED_EV_CENTS=3
```

Event-level caps (`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT`, `MAX_CONTRACTS_PER_EVENT`, `MAX_EVENT_EXPOSURE_CENTS`) are now implemented in `safety.py` and applied to both paper and shadow paths. For live trading these would still need to be reviewed separately.

## BUY YES / BUY NO implementation notes
Implemented behavior:
1. `signals` stores YES and NO quote fields, selected side, selected price, and fee-adjusted EV.
2. `paper_orders.side` and `demo_orders.side` contain `BUY_YES` or `BUY_NO`.
3. `paper_positions` keys positions by `(ticker, side)`.
4. `FeeModel` has generic binary buy fee/EV methods.
5. `SafetyGuard` checks side-aware position limits and NO price bounds.
6. `PaperTrader` evaluates both sides:
   - YES EV = `P(YES) * 100 - YES ask - fee`
   - NO EV = `(1 - P(YES)) * 100 - NO ask - fee`
   - It selects the higher executable fee-adjusted EV candidate.
7. `DemoExecutor.buy_no_fok()` maps BUY NO to an ASK on the YES book at `100 - NO price`, demo-only and fill-or-kill.
8. Dashboard shows selected side mix, order side mix, skip reasons, realized P/L, open exposure, and recent orders.

## Current skip behavior
High `no_executable_liquidity` is expected. Many weather ladder markets exist but have no executable size, especially outside the most active NYC hourly temperature markets. This skip means the bot saw a parseable signal but did not find enough ask size for the chosen side.

## Settlement / P&L tracking
Implemented local paper settlement reconciliation:
- `kalshi-weather-pnl` checks unsettled local paper-order tickers against Kalshi market results.
- `paper_orders` records settlement result, payout, realized P/L, and settlement JSON.
- Continuous runner reconciles P/L after each scan.
- Dashboard shows realized P/L, open exposure, win rate, P/L by side, and P/L over time.

## Production-market shadow tracking implemented
Implemented before any live trading:

1. Production/external market-data mode reads `https://external-api.kalshi.com/trade-api/v2` by default and does not submit orders.
2. SQLite tables store production quote/orderbook snapshots (`shadow_snapshots`) and shadow fills (`shadow_orders`).
3. Snapshots record production orderbook price, size, spread, market status, close time, selected side/price, EV, skip reason, and raw orderbook JSON.
4. Shadow fills are created only when production orderbook has executable liquidity for the selected side/price and fee-adjusted edge clears the configured threshold.
5. Shadow settlement/P&L is tracked separately from demo/local paper.
6. Dashboard now includes recent production-shadow snapshots and fills plus shadow P/L headline metrics.
7. Continuous runner can run it with `--production-shadow` at the recommended 15-minute cadence.

## Suggested next tasks
The infrastructure tasks are done (shadow tables/mode, event caps, dashboard comparison, calibration). The open work is now **model quality and risk controls**, because current post-reset production-shadow results are negative (see `observations.md` and the 2026-06-08 section above):
1. **Implement forecast bias correction** per station/series, variable, and target hour using stored `forecast_value` vs `result_value`; a global offset is misleading because cold and warm regimes cancel.
2. **Recalibrate/widen `probability._sigma`** from settled shadow errors, separately for hourly temp, daily high/low bands, and rain/no-rain behavior.
3. **Add adjacent-hour / same-day directional caps** for hourly temperature events so one persistent forecast-bias regime cannot create repeated same-direction losses across consecutive hours.
4. **Add an asymmetric-risk guard for expensive BUY_NO trades**, especially rain and one-degree bucket markets where one miss wipes out many small wins.
5. **Keep conservative forecast-uncertainty gating by default.** Do not extend relaxed temperature shadow trading as-is; any future relaxation should be bounded and read-only for calibration only.
6. **Backfill skipped high-EV outcomes** so "missed trades" can be evaluated by actual settlement/counterfactual P&L, not model EV alone.
7. **Monitor/fix stale unsettled shadow orders** (e.g. `shadow_orders.id=79` from the 2026-06-08 report) and add dashboard alerting for past-close `SHADOW_FILLED` rows.
8. (Lower priority) Export multi-day CSV/JSON; verify `result_value` extraction against settlement JSON.

## Caution for fresh agents
Do not enable live trading. The project is still research/demo/shadow only, **and the current algorithm is empirically unprofitable on production-shadow data** — fix forecast quality/calibration first.

Before modifying order submission, verify Kalshi API order direction docs. The current `DemoExecutor` is intentionally restricted to demo URLs and FOK orders.
