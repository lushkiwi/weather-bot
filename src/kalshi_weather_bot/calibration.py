from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field

from .config import Settings
from .storage import Store

# Joins settled orders to the probability that was predicted for them, so we can ask the
# only question that matters before live trading: are the model's probabilities calibrated,
# and is the forecast actually close to the realized weather?

PAPER_QUERY = """
SELECT s.probability_yes AS p, o.side AS side, o.settlement_result AS res,
       o.result_value AS rv, s.forecast_value AS fv,
       COALESCE(s.lookahead_risk, 0) AS look, o.ticker AS ticker,
       o.realized_pnl_cents AS pnl, s.event_ticker AS event_ticker
FROM paper_orders o JOIN signals s ON s.id = o.signal_id
WHERE o.status = 'SETTLED' AND s.probability_yes IS NOT NULL
"""

SHADOW_QUERY = """
SELECT ss.probability_yes AS p, o.side AS side, o.settlement_result AS res,
       o.result_value AS rv, ss.forecast_value AS fv,
       COALESCE(ss.lookahead_risk, 0) AS look, o.ticker AS ticker,
       o.realized_pnl_cents AS pnl, ss.event_ticker AS event_ticker
FROM shadow_orders o JOIN shadow_snapshots ss ON ss.id = o.snapshot_id
WHERE o.status = 'SHADOW_SETTLED' AND ss.probability_yes IS NOT NULL
"""

# Settled-but-skipped markets from the counterfactual backfill. This measures the model's
# decision quality (including the rain PoP model) on markets the gates refused to trade —
# with zero capital at risk, it is usually the largest verified sample available.
COUNTERFACTUAL_QUERY = """
SELECT ss.probability_yes AS p, co.selected_side AS side, co.settlement_result AS res,
       co.result_value AS rv, COALESCE(ss.raw_forecast_value, ss.forecast_value) AS fv,
       COALESCE(ss.lookahead_risk, 0) AS look, co.ticker AS ticker,
       co.counterfactual_pnl_cents AS pnl, ss.event_ticker AS event_ticker
FROM counterfactual_outcomes co JOIN shadow_snapshots ss ON ss.id = co.source_row_id
WHERE co.source = 'shadow' AND co.settlement_result IS NOT NULL
  AND ss.probability_yes IS NOT NULL AND co.selected_side IS NOT NULL
"""


@dataclass
class CalibrationReport:
    source: str
    n: int = 0
    n_events: int = 0
    brier: float | None = None
    log_loss: float | None = None
    win_rate: float | None = None
    mean_predicted: float | None = None
    total_pnl_cents: float = 0.0
    reliability: list[dict] = field(default_factory=list)
    forecast_mae: float | None = None
    forecast_bias: float | None = None
    forecast_rmse: float | None = None
    excluded_lookahead: int = 0


def _series_prefix(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def compute_calibration(store: Store, source: str = "paper", include_lookahead: bool = False, bins: int = 10) -> CalibrationReport:
    query = {"paper": PAPER_QUERY, "shadow": SHADOW_QUERY, "counterfactual": COUNTERFACTUAL_QUERY}[source]
    rows = [dict(r) for r in store.conn.execute(query).fetchall()]
    report = CalibrationReport(source=source)

    kept = []
    for r in rows:
        if not include_lookahead and int(r["look"] or 0) == 1:
            report.excluded_lookahead += 1
            continue
        kept.append(r)

    report.n = len(kept)
    if not kept:
        return report

    report.n_events = len({r["event_ticker"] or r["ticker"] for r in kept})
    report.total_pnl_cents = sum(float(r["pnl"] or 0.0) for r in kept)

    pairs = []  # (p_win, won)
    for r in kept:
        p = float(r["p"])
        side = str(r["side"])
        p_win = p if side == "BUY_YES" else 1.0 - p
        res = str(r["res"] or "").upper()
        won = 1.0 if ((side == "BUY_YES" and res == "YES") or (side == "BUY_NO" and res == "NO")) else 0.0
        pairs.append((p_win, won))

    report.brier = sum((p - w) ** 2 for p, w in pairs) / len(pairs)
    eps = 1e-9
    report.log_loss = -sum(w * math.log(max(p, eps)) + (1 - w) * math.log(max(1 - p, eps)) for p, w in pairs) / len(pairs)
    report.win_rate = sum(w for _, w in pairs) / len(pairs)
    report.mean_predicted = sum(p for p, _ in pairs) / len(pairs)

    # Reliability bins: predicted-probability buckets vs empirical hit rate.
    buckets: dict[int, list[tuple[float, float]]] = {}
    for p, w in pairs:
        idx = min(int(p * bins), bins - 1)
        buckets.setdefault(idx, []).append((p, w))
    for idx in sorted(buckets):
        group = buckets[idx]
        report.reliability.append({
            "bin": f"{idx / bins:.1f}-{(idx + 1) / bins:.1f}",
            "count": len(group),
            "mean_predicted": sum(p for p, _ in group) / len(group),
            "empirical": sum(w for _, w in group) / len(group),
        })

    # Forecast accuracy where a realized value was captured.
    errors = [float(r["fv"]) - float(r["rv"]) for r in kept if r["rv"] is not None and r["fv"] is not None]
    if errors:
        report.forecast_mae = sum(abs(e) for e in errors) / len(errors)
        report.forecast_bias = sum(errors) / len(errors)
        report.forecast_rmse = math.sqrt(sum(e * e for e in errors) / len(errors))

    return report


def format_report(report: CalibrationReport) -> str:
    lines = [f"=== Calibration: {report.source} ==="]
    if report.n == 0:
        lines.append("No settled outcomes yet (excluded_lookahead=%d)." % report.excluded_lookahead)
        return "\n".join(lines)
    lines.append(f"settled_orders={report.n}  independent_events={report.n_events}  excluded_lookahead={report.excluded_lookahead}")
    lines.append(f"brier={report.brier:.4f}  log_loss={report.log_loss:.4f}  (lower is better; 0.25 = coin flip)")
    lines.append(f"mean_predicted={report.mean_predicted:.3f}  empirical_win_rate={report.win_rate:.3f}  realized_pnl_cents={report.total_pnl_cents:.0f}")
    if report.forecast_mae is not None:
        lines.append(f"forecast_MAE={report.forecast_mae:.2f}  forecast_RMSE={report.forecast_rmse:.2f}  forecast_bias={report.forecast_bias:+.2f} (forecast - realized)")
    lines.append("reliability (predicted -> empirical):")
    for b in report.reliability:
        lines.append(f"  {b['bin']}: n={b['count']:>4}  predicted={b['mean_predicted']:.3f}  empirical={b['empirical']:.3f}")
    lines.append("NOTE: counts are correlated within an event; trust independent_events, not settled_orders, for power.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibration & forecast-error report for settled paper/shadow orders")
    parser.add_argument("--db", default="data/kalshi_weather.sqlite")
    parser.add_argument("--source", choices=["paper", "shadow", "counterfactual", "both", "all"], default="both")
    parser.add_argument("--include-lookahead", action="store_true", help="Include same-day/elapsed markets (leakage-inflated)")
    args = parser.parse_args(argv)

    store = Store(Settings().database_url or args.db)
    if args.source == "both":
        sources = ["paper", "shadow"]
    elif args.source == "all":
        sources = ["paper", "shadow", "counterfactual"]
    else:
        sources = [args.source]
    for source in sources:
        report = compute_calibration(store, source=source, include_lookahead=args.include_lookahead)
        print(format_report(report))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
