from __future__ import annotations

import argparse

from .config import Settings
from .kalshi_client import KalshiClient
from .storage import Store


def _production_settings(settings: Settings) -> Settings:
    overrides: dict[str, str] = {"kalshi_base_url": settings.kalshi_shadow_base_url}
    if settings.kalshi_shadow_api_key_id:
        overrides["kalshi_api_key_id"] = settings.kalshi_shadow_api_key_id
    if settings.kalshi_shadow_private_key_path:
        overrides["kalshi_private_key_path"] = settings.kalshi_shadow_private_key_path
    if settings.kalshi_shadow_private_key:
        overrides["kalshi_private_key"] = settings.kalshi_shadow_private_key
    return settings.model_copy(update=overrides)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill skipped high-EV outcomes and compute counterfactual P/L")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--source", choices=["paper", "shadow"], default="shadow")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-ev-cents", type=float, default=10.0)
    parser.add_argument("--skip-reason")
    parser.add_argument("--dry-run", action="store_true", help="List candidate skipped rows without fetching Kalshi or writing outcomes")
    args = parser.parse_args(argv)

    settings = Settings()
    store = Store(settings.database_url or args.db)
    candidates = store.counterfactual_candidates(
        source=args.source,
        min_ev_cents=args.min_ev_cents,
        limit=args.limit,
        skip_reason=args.skip_reason,
    )
    print(f"candidates={len(candidates)} source={args.source} min_ev={args.min_ev_cents:.1f}c dry_run={args.dry_run}")
    if not candidates:
        return 0
    for row in candidates[:10 if args.dry_run else len(candidates)]:
        print(
            f"{row['source_row_id']} {row['ticker']} {row['selected_side']} "
            f"price={row['selected_price_cents']} ev={row['fee_adjusted_ev_cents']} skip={row['skipped_reason']}"
        )
    if args.dry_run:
        return 0

    client_settings = _production_settings(settings) if args.source == "shadow" else settings
    client_settings.require_kalshi_auth()
    client = KalshiClient(client_settings)
    written = 0
    for row in candidates:
        market = client.get_market(str(row["ticker"]))
        store.upsert_counterfactual_outcome(
            source=args.source,
            source_row_id=int(row["source_row_id"]),
            ticker=str(row["ticker"]),
            selected_side=row.get("selected_side"),
            selected_price_cents=row.get("selected_price_cents"),
            fee_cents=row.get("fee_cents"),
            fee_adjusted_ev_cents=row.get("fee_adjusted_ev_cents"),
            skipped_reason=row.get("skipped_reason"),
            market=market,
        )
        written += 1
    print(f"wrote={written}")
    for summary in store.counterfactual_summary(args.source):
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
