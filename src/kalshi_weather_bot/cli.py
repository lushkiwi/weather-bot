from __future__ import annotations

import argparse
import json
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency installed in normal setup
    def load_dotenv() -> bool:
        return False

from .config import Settings
from .scanner import WeatherMarketScanner, signal_to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Kalshi weather market edge scanner")
    parser.add_argument("--limit", type=int, default=None, help="Maximum open markets to inspect")
    parser.add_argument("--min-edge-cents", type=float, default=None, help="Minimum YES edge to report")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of table text")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    settings = Settings()
    if args.min_edge_cents is not None:
        settings.min_edge_cents = args.min_edge_cents

    try:
        scanner = WeatherMarketScanner(settings)
        signals = scanner.scan(limit=args.limit)
    except Exception as exc:  # noqa: BLE001 - CLI should produce actionable message
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([signal_to_dict(s) for s in signals], indent=2))
    else:
        _print_table(signals)
    return 0


def _print_table(signals) -> None:
    if not signals:
        print("No qualifying Phase 1 weather edges found.")
        return
    print("ticker | edge¢ | fair¢ | mkt¢ | p_yes | city | date | threshold | title")
    print("-" * 120)
    for s in signals:
        print(
            f"{s.ticker} | {s.edge_cents:5.1f} | {s.fair_yes_cents:5.1f} | "
            f"{s.market_yes_cents:5.1f} | {s.probability_yes:0.3f} | {s.city} | "
            f"{s.target_date.isoformat()} | {s.variable.value} {s.threshold:g} | {s.title[:80]}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
