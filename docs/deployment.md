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

## Next implementation steps

1. Add a Postgres-backed `Store` implementation, while keeping SQLite for local dev.
2. Add config such as `DATABASE_URL` or `SUPABASE_DB_URL`.
3. Make the runner write to Supabase Postgres in hosted mode.
4. Build or adapt the dashboard for Vercel:
   - Option A: Next.js dashboard reading Supabase from server-side routes.
   - Option B: keep the current Python dashboard and host it on Railway/Fly instead of Vercel.
5. Deploy the runner separately:
   - Railway/Fly/Render as a worker process, or
   - GitHub Actions cron running `kalshi-weather-runner --once --production-shadow` every 15 minutes.

## Recommended path

For the cleanest setup:

1. Supabase Postgres for data.
2. Railway or Fly.io for the Python runner.
3. Vercel + Next.js for the dashboard.
4. Keep live trading disabled; production shadow remains read-only.
