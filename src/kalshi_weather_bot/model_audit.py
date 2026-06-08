from __future__ import annotations

import argparse
import math
from collections import defaultdict
from dataclasses import dataclass

from .config import Settings
from .storage import Store

PAPER_ROWS = """
SELECT o.ticker, o.side, o.settlement_result, o.realized_pnl_cents AS pnl,
       o.result_value AS rv, s.forecast_value AS fv, s.probability_yes AS p,
       COALESCE(s.lookahead_risk, 0) AS look, s.variable AS variable, s.target_hour AS target_hour,
       s.band_lower AS band_lower, s.band_upper AS band_upper
FROM paper_orders o JOIN signals s ON s.id = o.signal_id
WHERE o.status = 'SETTLED' AND s.probability_yes IS NOT NULL
"""

SHADOW_ROWS = """
SELECT o.ticker, o.side, o.settlement_result, o.realized_pnl_cents AS pnl,
       o.result_value AS rv, s.forecast_value AS fv, s.probability_yes AS p,
       COALESCE(s.lookahead_risk, 0) AS look, s.variable AS variable, s.target_hour AS target_hour,
       s.band_lower AS band_lower, s.band_upper AS band_upper
FROM shadow_orders o JOIN shadow_snapshots s ON s.id = o.snapshot_id
WHERE o.status = 'SHADOW_SETTLED' AND s.probability_yes IS NOT NULL
"""


@dataclass
class GroupStats:
    n: int = 0
    clean_n: int = 0
    wins: int = 0
    pnl: float = 0.0
    pred_sum: float = 0.0
    brier_sum: float = 0.0
    errors: list[float] | None = None

    def add(self, row: dict) -> None:
        if self.errors is None:
            self.errors = []
        side = str(row["side"])
        p_yes = float(row["p"])
        p_win = p_yes if side == "BUY_YES" else 1.0 - p_yes
        result = str(row.get("settlement_result") or "").upper()
        won = 1 if ((side == "BUY_YES" and result == "YES") or (side == "BUY_NO" and result == "NO")) else 0
        self.n += 1
        self.clean_n += 0 if int(row.get("look") or 0) else 1
        self.wins += won
        self.pnl += float(row.get("pnl") or 0.0)
        self.pred_sum += p_win
        self.brier_sum += (p_win - won) ** 2
        if row.get("rv") is not None and row.get("fv") is not None:
            self.errors.append(float(row["fv"]) - float(row["rv"]))

    def render(self, key: tuple) -> str:
        errors = self.errors or []
        mae = sum(abs(e) for e in errors) / len(errors) if errors else None
        bias = sum(errors) / len(errors) if errors else None
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None
        sigma_candidate = rmse * 1.75 if rmse is not None else None
        return (
            f"{key[0]:<12} {key[1]:<12} {str(key[2]):<5} {key[3]:<8} "
            f"n={self.n:<3} clean={self.clean_n:<3} wins={self.wins:<3} "
            f"p_mean={self.pred_sum / self.n:.3f} win_rate={self.wins / self.n:.3f} "
            f"brier={self.brier_sum / self.n:.3f} pnl={self.pnl:+.0f}c "
            f"mae={mae:.2f} bias={bias:+.2f} rmse={rmse:.2f} sigma≈{sigma_candidate:.2f}"
            if errors
            else f"{key[0]:<12} {key[1]:<12} {str(key[2]):<5} {key[3]:<8} n={self.n:<3} clean={self.clean_n:<3} wins={self.wins:<3} p_mean={self.pred_sum / self.n:.3f} win_rate={self.wins / self.n:.3f} brier={self.brier_sum / self.n:.3f} pnl={self.pnl:+.0f}c mae=— bias=— rmse=— sigma≈—"
        )


def _series(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def _variable(row: dict) -> str:
    if row.get("variable"):
        return str(row["variable"])
    ticker = str(row.get("ticker") or "")
    if "RAIN" in ticker:
        return "rain_in"
    if "LOW" in ticker:
        return "low_temp_f"
    if "HIGH" in ticker:
        return "high_temp_f"
    if "TEMP" in ticker:
        return "point_temp_f"
    return "unknown"


def compute_groups(store: Store, source: str) -> dict[tuple, GroupStats]:
    query = PAPER_ROWS if source == "paper" else SHADOW_ROWS
    groups: dict[tuple, GroupStats] = defaultdict(GroupStats)
    for row in [dict(r) for r in store.conn.execute(query).fetchall()]:
        variable = _variable(row)
        hour = row.get("target_hour") if variable == "point_temp_f" else None
        kind = "band" if row.get("band_lower") is not None and row.get("band_upper") is not None else "threshold"
        if variable == "rain_in":
            kind = "rain"
        key = (_series(str(row["ticker"])), variable, hour, kind)
        groups[key].add(row)
    return groups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline model calibration/sigma audit by series/variable/hour")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--source", choices=["paper", "shadow", "both"], default="shadow")
    args = parser.parse_args(argv)

    store = Store(Settings().database_url or args.db)
    sources = ["paper", "shadow"] if args.source == "both" else [args.source]
    for source in sources:
        print(f"=== Model audit: {source} ===")
        groups = compute_groups(store, source)
        if not groups:
            print("No settled rows.\n")
            continue
        print("series       variable     hour  kind     metrics")
        for key in sorted(groups):
            print(groups[key].render(key))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
