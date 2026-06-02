# Kalshi Weather Bot

Weather-market scanner, local paper trader, BUY YES/BUY NO evaluator, Kalshi demo execution backend, continuous runner, and web dashboard.

Current operating mode: demo execution plus local paper tracking plus **production-market shadow tracking**: read real Kalshi production orderbooks, never place production orders, and measure whether the algorithm's demo/paper edges are actually executable in the real market over several days.

For fresh-agent handoff, start with `PROJECT_STATUS.md`, then `plan.md`.

## Hosting (cloud)

This bot is deployed on **Railway** (a `*/10 * * * *` cron `runner` service + an always-on
`dashboard` service) backed by **Supabase Postgres**, with code on GitHub. The cron runs
`--shadow-only` (read-only production shadow; no demo orders, no live trading). See
[`docs/deployment.md`](docs/deployment.md) for the full architecture, service IDs, env vars, and
operating notes. The instructions below are for **local development**, which still uses SQLite.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate            # macOS/Linux; Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -e .
cp .env.example .env
```

Fill in `.env` with Kalshi credentials. Leave `DATABASE_URL` blank for local SQLite; set it to a
Supabase/Postgres connection string to run against hosted Postgres (the `Store` switches backends
automatically).

## Required environment

```bash
KALSHI_API_KEY_ID=your-key-id
KALSHI_PRIVATE_KEY_PATH=C:/path/to/kalshi_private_key.pem
# or, less recommended, one quoted line with escaped newlines:
# KALSHI_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

Optional:

```bash
KALSHI_BASE_URL=https://demo-api.kalshi.co/trade-api/v2
KALSHI_SHADOW_BASE_URL=https://external-api.kalshi.com/trade-api/v2
# Production read-only creds for shadow tracking. The external/production API rejects demo
# keys, so these must be a real production key/key-file. They fall back to the primary
# KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH if blank.
KALSHI_SHADOW_API_KEY_ID=your-production-key-id
KALSHI_SHADOW_PRIVATE_KEY_PATH=C:/path/to/production_key.pem
# With KALSHI_SERIES_TICKERS set, this is the max markets fetched per weather series.
KALSHI_MARKET_LIMIT=50
KALSHI_SERIES_TICKERS=KXTEMPNYCH,KXTEMPCHIH,KXTEMPBOSH,KXTEMPDCH,KXTEMPLAXH,KXTEMPMIAH,KXHIGHAUS,KXHIGHCHI,KXHIGHDEN,KXHIGHHOU,KXPHILHIGH,KXHIGHTSEA,KXHIGHTSFO,KXHIGHNY,KXHIGHMIA,KXLOWTAUS,KXLOWTCHI,KXLOWTBOS,KXLOWNYC,KXLOWLAX,KXRAINAUSM,KXRAINCHIM,KXRAINDALM,KXRAINHOUM,KXRAINLAXM,KXRAINMIAM,KXRAINNYC
MIN_EDGE_CENTS=3
# Hosted Postgres (Supabase). Blank = local SQLite. When set, every CLI uses Postgres.
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres
```

## Run

```bash
kalshi-weather-scan --limit 100
```

Or:

```bash
python -m kalshi_weather_bot.cli --limit 100
```

## Targeted weather series scanner

The scanner no longer grabs the first N open Kalshi markets. It filters `/markets` by configured weather `series_ticker` values.

`KALSHI_MARKET_LIMIT` is now interpreted as **markets per configured series**, not total markets. A lower value like `50` is usually enough because the bot is no longer wasting the limit on unrelated markets.

Configured series include NYC hourly temperature plus popular/weather-active city daily high/low/rain series such as Chicago, Austin, Boston, DC, LA, Miami, Denver, Houston, Philadelphia, Seattle, San Francisco, and Dallas.

## Phase 2 local paper trading

This records signals, fee-adjusted EV, hypothetical fills, and local paper positions in SQLite. It still does **not** submit Kalshi orders.

```bash
python -m kalshi_weather_bot.paper_cli --limit 50
```

Database (local dev = SQLite; cloud = Supabase Postgres via `DATABASE_URL`):

```text
data/kalshi_weather.sqlite
```

Fresh-lens reset: previous runtime data was archived on 2026-05-29 to:

```text
data/archive/kalshi_weather_20260529_134719.sqlite
data/archive/kalshi_weather_20260529_134719_manifest.json
data/archive/kalshi_weather_20260529_134719_summary.md
```

The live database was cleared after archiving. Treat new dashboard/calibration results as post-reset only unless you intentionally query the archive.

## Kalshi demo execution

Phase 2.5 can optionally submit qualifying fill-or-kill BUY YES and BUY NO orders to the Kalshi demo API. It refuses non-demo base URLs.

Important: Kalshi demo is **not** the same as the real production market. Demo fills/wins validate the bot plumbing, safety checks, settlement logic, and dashboard, but they do not prove live profitability. Production-market shadow tracking is required before any live move.

Preview/snapshot demo account:

```bash
python -m kalshi_weather_bot.demo_cli --snapshot
```

Submit qualifying demo orders, only when local Phase 2 would have filled:

```bash
python -m kalshi_weather_bot.demo_cli --limit 50 --execute-demo
```

## Continuous week-long test runner

Run one iteration:

```bash
kalshi-weather-runner --limit 50 --execute-demo --once
```

Run dashboard plus automatic demo scanner/trader in one command:

```bash
python -m kalshi_weather_bot.app --port 8787 --limit 50 --execute-demo --interval-seconds 900
```

Or use the batch helper:

```bash
start_demo_bot.bat
```

Run only the background scanner/trader every 15 minutes:

```bash
kalshi-weather-runner --limit 50 --execute-demo --interval-seconds 900
```

Safety defaults are moderately aggressive for demo testing. Local `.env` may be temporarily raised for demo-only experiments, but live settings should be much stricter:

```env
MAX_ORDERS_PER_DAY=20
MAX_CONTRACTS_PER_MARKET=3
# Event-level caps treat one city/day/hour's correlated strike ladder as a single risk.
MAX_CONTRACTS_PER_EVENT=1
DISALLOW_MULTIPLE_POSITIONS_PER_EVENT=true
MAX_EVENT_EXPOSURE_CENTS=1500
MAX_TOTAL_EXPOSURE_CENTS=5000
ORDER_COOLDOWN_MINUTES=240
DISALLOW_OPPOSITE_SIDE_SAME_MARKET=true
# Avoid turning noisy forecast tails into a low-win-rate stream of 1c/4c longshots.
MIN_TRADE_PROBABILITY=0.55
MIN_YES_ASK_CENTS=1
MAX_YES_ASK_CENTS=97
MIN_NO_ASK_CENTS=1
MAX_NO_ASK_CENTS=97
# Forecast-quality risk controls (2026-05-28). Only the single best-EV strike per correlated
# event is traded, and temperature markets the forecast cannot resolve are skipped.
BEST_STRIKE_PER_EVENT=true
FORECAST_UNCERTAINTY_GATE_RATIO=1.0   # conservative; raise only for bounded shadow experiments
DEFAULT_STRIKE_SPACING_F=1.0
```

## Demo vs local exposure note

Local paper orders are only counted as open exposure when they remain `FILLED` and unsettled. If demo execution rejects an order, the matching local order is marked `DEMO_REJECTED` so it does not inflate dashboard open exposure.

## Production-market shadow tracking

Phase 2.75 observes real production markets without live execution:

1. Reads production/external Kalshi orderbooks for configured weather series.
2. Stores production quote/orderbook snapshots in SQLite (`shadow_snapshots`).
3. Creates shadow fills only when production liquidity is executable at the selected side/price (`shadow_orders`).
4. Tracks shadow P/L and win rate separately from demo/local paper.
5. Records production prices, spreads, sizes, market status, close time, and raw orderbook JSON.
6. Keeps production order submission disabled by design.

Run one production-shadow pass:

```bash
kalshi-weather-shadow --limit 50 --settle
```

Run continuously every 15 minutes alongside local/demo monitoring:

```bash
kalshi-weather-runner --limit 50 --execute-demo --production-shadow --interval-seconds 900
```

A 15-minute cadence is acceptable for the first production-shadow run. Faster 3–5 minute scans may be needed later for near-close hourly temperature markets.

**Shadow-only mode (what the cloud cron runs):** `--shadow-only` skips the demo-API paper scan and
the demo client entirely, running just the read-only production shadow scan + settlement. It needs
only production read credentials, which is why it is the deployed cron command:

```bash
kalshi-weather-runner --once --production-shadow --shadow-only --limit 50
```

## Paper settlement / P&L

Reconcile settled Kalshi markets and update local paper P/L:

```bash
kalshi-weather-pnl
```

The continuous runner also runs settlement reconciliation after each scan.

## Calibration / forecast-error report

Once paper or shadow orders have settled, score whether the model's probabilities are
trustworthy (this is the go/no-go signal before any live trading):

```bash
kalshi-weather-calib --source shadow
kalshi-weather-calib --source both --include-lookahead
```

Reports Brier score, log loss, reliability bins (predicted vs empirical hit rate),
forecast MAE/bias, and independent-event counts. Same-day "leakage" rows
(`lookahead_risk=1`) are excluded by default. The dashboard shows the headline metrics in a
"Model calibration" tile.

## Web dashboard

Start the local UI:

```bash
python -m kalshi_weather_bot.web_ui --port 8787
```

Then open:

```text
http://127.0.0.1:8787
```

In the cloud the same dashboard runs on Railway (binds `0.0.0.0:$PORT`, reads Supabase) at its
generated `*.up.railway.app` URL — see `docs/deployment.md`.

The dashboard shows scan counts, graphs, skip reasons, selected side mix, YES/NO paper orders, demo orders, production-shadow snapshots/fills, cooldown/safety skips, realized P/L, open exposure, win rate, P/L by side, and open local paper positions. It also has a button to run a new local paper scan.

## Safety

Phase 1 never places orders. Phase 2 local paper mode also never places Kalshi orders; it only simulates fills and stores them locally.

Do not enable live trading based on demo win rate alone. Demo markets can be stale/thin and are not a sufficient test of real-world execution quality.

The first 18 settled shadow fills went 4 wins / 14 losses (-74¢). A from-the-data audit (see `PROJECT_STATUS.md` → "risk-control fixes") found the dominant cause was **correlated-ladder over-betting** — the bot stacked up to 6 same-direction bets on one event, so a single wrong forecast lost on every strike — compounded by an overconfident `sigma` and an edge gate that ignored forecast uncertainty. Fixes shipped:

- `BEST_STRIKE_PER_EVENT=true` — place only the single best fee-adjusted-EV order per event (the main loss guard; backtest ≈10–12× less loss).
- Recalibrated, wider `probability._sigma` (from realized forecast error).
- `FORECAST_UNCERTAINTY_GATE_RATIO` — skip temperature markets where `sigma ≥ ratio × strike_spacing`. Runtime `.env` is back to the conservative `1.0`; raise it only for bounded shadow-data experiments.

A follow-up audit found two additional causes of the low win rate: repeated scans could still add more strikes from the same event, and the EV selector favored cheap low-probability tail bets. Current defaults therefore allow only one order per event (`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT=true`, `MAX_CONTRACTS_PER_EVENT=1`) and require `MIN_TRADE_PROBABILITY=0.55`.

The model is still **not** ready for live trading. Open work is forecast bias-correction and re-calibration (`kalshi-weather-calib --source shadow`) after more days, not execution.
