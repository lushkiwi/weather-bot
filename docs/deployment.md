# Web deployment plan

This repo is now linked to a Supabase project named `weather-bot`. Supabase should hold runtime data; GitHub should hold code and database migrations.

## Target architecture

```text
GitHub private repo
  ├─ Supabase Postgres: scans/signals/orders/shadow data
  ├─ Vercel: dashboard / read-only API
  └─ Background runner: Railway, Fly.io, Render, or GitHub Actions cron
```

Do **not** put long-running bot loops on Vercel serverless. Use Vercel for the dashboard and deploy the Python runner separately.

## Supabase

Local setup:

```bash
supabase link --project-ref xtttchcsmlzjsxcnrttb
supabase db push
```

Committed migration:

```text
supabase/migrations/20260601052455_initial_weather_bot_schema.sql
```

The schema mirrors the current SQLite ledger tables:

- `scans`
- `signals`
- `paper_orders`
- `paper_positions`
- `demo_orders`
- `demo_snapshots`
- `shadow_snapshots`
- `shadow_orders`
- `runner_events`

RLS is enabled and no public policies are created. Backend services should use direct Postgres credentials or the Supabase service-role key. Do not expose the service-role key in browser code.

## Secrets

Never commit:

- `.env`
- Kalshi private keys (`*.pem`, `*.key`, backups)
- SQLite files / runtime data
- Supabase service-role key
- Postgres connection strings containing passwords

Use environment variables in Vercel/Railway/Fly/Render/GitHub Actions.

## Deployed architecture (live)

The cloud migration is implemented and running:

```text
GitHub (lushkiwi/weather-bot, branch main)
  └─ Railway project "weather-bot"  (workspace: lushkiwi's Projects)
       ├─ service "runner"     — cron `*/10 * * * *`, restart NEVER
       │     start: python -m kalshi_weather_bot.runner --once --production-shadow --shadow-only --limit 50
       └─ service "dashboard"  — always-on web, public domain
             start: python -m kalshi_weather_bot.web_ui --host 0.0.0.0   (binds $PORT)
  └─ Supabase Postgres (project weather-bot, ref xtttchcsmlzjsxcnrttb): all ledger tables
```

- **Database**: `storage.py` `Store` is dual-backend. Set `DATABASE_URL` (Supabase session-pooler
  URI) → Postgres; leave blank → local SQLite for dev. The committed migration
  (`supabase/migrations/20260601052455_initial_weather_bot_schema.sql`) is already applied to the
  hosted project.
- **Build**: `Dockerfile` (`pip install .` on `python:3.11-slim`) — chosen over Nixpacks because
  Nixpacks left the package uninstalled, so the console scripts were missing.
- **Runner mode**: `--shadow-only` skips the demo-API paper path entirely and runs only the
  read-only production shadow scan + settlement, so the cron needs only production read creds
  (`KALSHI_SHADOW_API_KEY_ID` + `KALSHI_SHADOW_PRIVATE_KEY`). **No live trading; no demo orders.**
- **Dashboard**: same image, hosted as a second Railway service with a generated `*.up.railway.app`
  domain. It reads Supabase and renders the production-shadow stats (plus paper/demo panes).

### Required Railway variables (both services)

`DATABASE_URL`, `KALSHI_SHADOW_API_KEY_ID`, `KALSHI_SHADOW_PRIVATE_KEY` (inline PEM),
`KALSHI_SHADOW_BASE_URL`, the series/limit/edge config, and the safety/gate vars
(`BEST_STRIKE_PER_EVENT`, `FORECAST_UNCERTAINTY_GATE_RATIO`,
`SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO`, `SHADOW_GATE_EXPERIMENT_UNTIL`, `MIN_TRADE_PROBABILITY`,
`MAX_*`, `DISALLOW_*`). The dashboard additionally sets `PORT=8080`. Never commit these.

### Operating notes

- Pushing to `main` redeploys (Railway is connected to the GitHub repo).
- **Shadow gate experiment** `SHADOW_GATE_EXPERIMENT_UNTIL` controlled how long the relaxed shadow
  gate (`SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO=6.0`) recorded temperature markets. After that date
  the conservative gate blocks ~all temperature ladders and shadow records little. The 2026-06-08
  shadow review found the collected fills were negative and poorly calibrated, so do **not** bump the
  Railway var to keep collecting as-is; any future extension should be an explicitly bounded,
  read-only calibration experiment. Per `CLAUDE.md`, fills in this window are calibration data, not edge.
- Local dev still works with no `DATABASE_URL` (SQLite) and `kalshi-weather-*` commands.

A Vercel + Next.js dashboard remains a possible future upgrade, but the Python dashboard on Railway
covers the need today without a rewrite.
