from __future__ import annotations

import argparse

from dotenv import load_dotenv

from .config import Settings
from .pnl import reconcile_paper_settlements
from .storage import Store


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Reconcile paper-trade settlements and P/L")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--limit", type=int, default=None, help="Max unsettled markets to check")
    args = parser.parse_args(argv)

    result = reconcile_paper_settlements(Settings(), Store(args.db), limit=args.limit)
    print(f"markets_checked: {result.markets_checked}")
    print(f"orders_settled: {result.orders_settled}")
    print(f"errors: {result.errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
