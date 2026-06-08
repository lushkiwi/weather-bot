# Shadow-run observations

**Generated:** 2026-06-08 00:51 UTC
**Database:** Supabase project `weather-bot` (`xtttchcsmlzjsxcnrttb`), queried live via `supabase db query --linked`.
**Scope:** current post-reset production-shadow ledger (`shadow_snapshots`, `shadow_orders`, `scans`, `runner_events`). Counts continue changing as Railway cron runs every ~10 minutes.
**Supersedes:** the 2026-06-03 02:25 UTC report below. This update adds ~5 more days of shadow scans, resolves the first clean non-lookahead fills, and changes the headline from "small lookahead-contaminated profit" to **clearly negative shadow performance**.

## Executive summary

The bot is still operationally healthy and still shadow-only/read-only, but the current production-shadow results are not viable:

- **83 total shadow fills:** 79 settled, 4 open.
- **Settled P/L:** **−469¢ / −$4.69** on 2,169¢ cost basis (**−21.6% ROI**).
- **Win rate:** **17/79 = 21.5%**, despite average model win probability **69.3%**.
- **Calibration:** Brier **0.386**, log loss **0.991** — both worse than the naive 0.25 Brier coin-flip baseline.
- **Clean/non-lookahead settled fills now exist:** 7 rows, **−172¢**, 4/7 wins, average predicted win probability **90.7%**. The first clean evidence is negative, not merely inconclusive.
- **No live/demo orders in cloud:** `paper_orders=0`, `demo_orders=0`; all "trades" here are production-shadow simulations.

Bottom line: the earlier +195¢ was a transient, lookahead-contaminated midday windfall. With more settlements, the strategy has flipped decisively negative. The old same-event ladder bug remains fixed, but the bot is consistently making overconfident, source-biased weather bets and high-cost NO bets where one miss wipes out many small wins.

## Comparison to the 2026-06-03 report

| Metric | 2026-06-03 02:25 UTC | 2026-06-08 00:51 UTC | Change |
|---|---:|---:|---:|
| Shadow scans | 128 | **839** | +711 |
| Shadow snapshots | 4,405 | **21,949** | +17,544 |
| Shadow fills | 21 | **83** | +62 |
| Settled fills | 16 | **79** | +63 |
| Open fills | 5 | **4** | −1 |
| Settled win rate | 37.5% | **21.5%** | worse |
| Settled P/L | +195¢ | **−469¢** | −664¢ |
| Settled cost basis | 405¢ | **2,169¢** | +1,764¢ |
| Open exposure incl. fee | 334¢ | **314¢** | −20¢ |
| Settled non-lookahead rows | 0 | **7** | +7 |
| Non-lookahead P/L | n/a | **−172¢** | negative first clean sample |

The model expected large positive value: settled rows had about **+3,303¢** of summed model fee-adjusted EV, while realized P/L was **−469¢**. The EV estimates are therefore not calibrated enough to use as trading evidence.

## Placed shadow fills by segment

| Segment | Settled | Wins | P/L | Cost basis | Mean p_win | Forecast MAE / bias |
|---|---:|---:|---:|---:|---:|---:|
| All settled | 79 | 17 | **−469¢** | 2,169¢ | 0.693 | MAE 2.91°F, bias −0.15°F |
| Lookahead-risk rows | 72 | 13 | **−297¢** | 1,597¢ | 0.672 | MAE 3.10°F, bias −0.21°F |
| Clean non-lookahead rows | 7 | 4 | **−172¢** | 572¢ | 0.907 | MAE 0.89°F, bias +0.45°F |

By series:

| Series | Settled | Wins | P/L | Cost basis | Notes |
|---|---:|---:|---:|---:|---|
| `KXTEMPNYCH` hourly temp | 69 | 11 | **−245¢** | 1,345¢ | Forecast MAE 3.22°F vs 1°F strikes; direction follows source bias. |
| `KXHIGHCHI` daily high buckets | 5 | 2 | **−177¢** | 377¢ | All BUY_NO on narrow bands; high price paid to win small payouts. |
| `KXRAINNYC` daily rain | 5 | 4 | **−47¢** | 447¢ | Four small NO wins could not offset one rain miss (−68¢). |

By side:

| Side | Settled | Wins | P/L | Cost basis | Mean p_win | Mean forecast bias |
|---|---:|---:|---:|---:|---:|---:|
| BUY_NO | 47 | 10 | **−432¢** | 1,432¢ | 0.726 | −2.44°F |
| BUY_YES | 32 | 7 | **−37¢** | 737¢ | 0.644 | +3.22°F |

BUY_NO is now the dominant loss source. For hourly temp, the model buys NO when Open-Meteo is too cold; for rain/bands it often pays 60–95¢ to win a small residual payout. That asymmetric payoff profile is not protected by the current `MIN_TRADE_PROBABILITY` floor.

## Clean/non-lookahead fills

These are the first go/no-go-quality rows after the baseline report:

| ID | Ticker | Side | p_win | Cost | Result | P/L | Note |
|---:|---|---|---:|---:|---|---:|---|
| 12 | `KXHIGHCHI-26JUN03-B82.5` | BUY_NO | 0.868 | 73¢ | YES | **−73¢** | Actual landed in the bucket. |
| 14 | `KXRAINNYC-26JUN03-T0` | BUY_NO | 0.990 | 96¢ | NO | +4¢ | Correct no-rain, tiny payout. |
| 31 | `KXHIGHCHI-26JUN04-B86.5` | BUY_NO | 0.871 | 84¢ | YES | **−84¢** | Actual landed in the bucket. |
| 51 | `KXHIGHCHI-26JUN05-B82.5` | BUY_NO | 0.881 | 77¢ | NO | +23¢ | Bucket missed. |
| 52 | `KXRAINNYC-26JUN05-T0` | BUY_NO | 0.990 | 93¢ | NO | +7¢ | Correct no-rain, tiny payout. |
| 73 | `KXHIGHCHI-26JUN06-B81.5` | BUY_NO | 0.957 | 81¢ | NO | +19¢ | Bucket missed. |
| 76 | `KXRAINNYC-26JUN06-T0` | BUY_NO | 0.790 | 68¢ | YES | **−68¢** | Open-Meteo had 0 precip; settlement recorded 0.26. |

The clean sample is small, but it already rejects the "maybe shadow is profitable once lookahead is removed" hope. The non-lookahead rows are high-confidence on paper (mean p_win 0.907) and still lost money.

## Calibration and reliability

| Predicted p_win bin | N | Mean predicted | Empirical win rate | P/L |
|---|---:|---:|---:|---:|
| 0.5–0.6 | 24 | 0.582 | 0.208 | +1¢ |
| 0.6–0.7 | 24 | 0.644 | 0.208 | −100¢ |
| 0.7–0.8 | 16 | 0.748 | **0.000** | **−271¢** |
| 0.8–0.9 | 10 | 0.842 | 0.200 | −139¢ |
| 0.9–1.0 | 5 | 0.981 | 1.000 | +40¢ |

The middle/high-confidence region is severely miscalibrated: p_win 0.7–0.9 went 2/26 and lost 410¢. The only reliable-looking bin is tiny and mostly rain/no-rain pennies.

## Forecast-error pattern

The diurnal source-bias finding from the prior report persists and is now stronger:

- Overnight/early morning hourly NYC forecasts are too cold: the bot buys NO and reality is warmer, causing repeated losses.
- Midday through afternoon forecasts became too warm on later days: the bot buys YES and reality is cooler, causing another loss cluster.
- Overall bias (−0.15°F) hides the problem because cold and warm regimes cancel. A global offset would not fix it.
- Hourly forecast MAE is **3.22°F** on 1°F strike spacing, which is far too large for the current ladder strategy.

Worst hourly clusters:

| Target hours | Pattern | P/L |
|---|---|---:|
| 00–05 | mostly BUY_NO on cold-biased forecasts | **−170¢** combined |
| 13–17 | mostly BUY_YES on warm-biased forecasts | **−169¢** combined |
| 22–23 | late BUY_NO cold-bias cluster | **−184¢** combined |

The previous correlated-ladder bug was "many strikes in one event." The current failure is **many adjacent hourly events in the same bias regime**. Event-level lockout cannot stop that.

## Missed/skipped opportunities

Current production-shadow skip mix:

| Skip reason | Snapshots | % | Distinct events | Avg model EV | Interpretation |
|---|---:|---:|---:|---:|---|
| `probability_below_min_trade_probability` | 13,580 | 61.87% | 101 | +0.89¢ | Probability floor is doing most filtering. |
| `not_best_strike_in_event` | 2,642 | 12.04% | 90 | +12.09¢ | Best-strike-per-event is active; not a true miss. |
| `forecast_uncertainty_exceeds_strike_spacing` | 2,093 | 9.54% | 6 | +18.08¢ | Conservative gate blocking high/low temp ladders after experiment. |
| `no_executable_production_liquidity` | 1,312 | 5.98% | 72 | +41.33¢ | Apparent model edges without executable size. |
| `production_event_already_traded` | 1,136 | 5.18% | 44 | +40.61¢ | Across-scan event lockout is active. |
| `production_insufficient_fee_adjusted_edge` | 606 | 2.76% | 52 | −1.95¢ | Correctly rejected by EV floor. |
| `production_cooldown_same_market_side` | 307 | 1.40% | 56 | +31.25¢ | Cooldown is active. |
| `production_max_orders_per_day` | 190 | 0.87% | 18 | +35.69¢ | Daily cap is active. |
| filled shadow order | 83 | 0.38% | 83 | — | Very selective. |

Important: these are **model-missed**, not proven profitable misses. Because the model's realized calibration is poor, a skipped row with high model EV is not strong evidence of a missed edge. The ledger also does not currently settle skipped tickers, so we cannot fully answer "would skipped trades have won?" without fetching/backfilling settlement outcomes for skipped snapshots.

Actionable improvement: add an offline missed-trade audit that backfills settlement results for high-EV skipped snapshots and computes counterfactual P/L by skip reason. Until then, treat the skip table mainly as safety/coverage diagnostics.

## Safety/regression checks

Good news:

- **Old same-event ladder stacking remains fixed:** no `event_ticker` has more than one shadow order.
- **Low-probability tail-bet floor remains fixed:** 0 filled orders have side-aware p_win < 0.55.
- Runner is healthy: 144 scans in the last 24h, average gap 10.00 minutes, max gap 10.82 minutes, 0 gaps >20 minutes, 0 runner errors in the last 24h.
- Latest scan was `scan_id=839`, `shadow_markets=164`, `shadow_snapshots=14`, `shadow_fills=0`, `shadow_market_errors=0`.

Issues:

- **One stuck past-close open:** `shadow_orders.id=79` (`KXTEMPNYCH-26JUN0521-T79.99`, BUY_NO, cost 68¢) has `close_time=2026-06-06 01:00 UTC` but is still `SHADOW_FILLED` as of this report. It may be an upstream unsettled/active market, but it should be monitored and investigated.
- Only three series currently have persisted snapshots (`KXTEMPNYCH`, `KXHIGHCHI`, `KXRAINNYC`) even though the runner is configured for 27 series. This may simply reflect available/open/parseable markets, but if broader coverage matters, add series-level "no markets / unparseable / no tradeable market" logging.
- After the 2026-06-06 shadow-gate experiment ended, temperature fills effectively stopped; recent scans are mostly conservative-gate skips for `KXHIGHCHI` and rain/event-lockout rows. That is safer, but it also means further temperature calibration will stall unless the experiment is deliberately extended.

## Consistent mistakes the bot is making

1. **Overconfident probabilities.** Mean predicted p_win is 69.3% vs 21.5% actual. Clean rows are even more overconfident (90.7% predicted vs 57.1% actual and negative P/L).
2. **Open-Meteo/source basis dominates 1°F ladders.** The hourly NYC forecast error is multiple degrees against 1°F strikes. The model's side selection follows the bias into losing regimes.
3. **Adjacent-hour correlation is uncontrolled.** Per-event caps stop one strike ladder from exploding, but they do not stop repeated same-direction hourly bets when the forecast source is biased for several consecutive hours.
4. **High-priced BUY_NO risk is underestimated.** Rain and one-degree bucket NO trades look high-probability but have poor payoff asymmetry; one weather miss wipes out many small wins.
5. **Band-bucket probabilities are still not decision-safe.** For `KXHIGHCHI`, the bot repeatedly bought NO on narrow buckets near the forecast because the continuous normal model assigns low exact-bucket probability. Actual settlement landed in the bucket often enough to make this very negative.
6. **The EV gate trusts the model too much.** Large positive model EV did not translate to realized edge; skip/fill decisions should be treated as model diagnostics, not trading truth.

## Recommendations

Priority order:

1. **Keep live trading disabled.** Current production-shadow evidence is negative, including the first clean non-lookahead sample.
2. **Do not extend relaxed temperature shadow trading as-is.** If more calibration data is needed, extend only as a bounded read-only experiment with explicit daily loss/row caps and labels. Conservative gate behavior is currently protecting the bot from more hourly temperature damage.
3. **Implement per-station/per-variable/per-hour bias correction before any further temp strategy claims.** Global bias is misleading; correction must be keyed by station/series and target hour.
4. **Add consecutive-hour / same-day directional caps.** Example: max N same-direction `KXTEMPNYCH` hourly fills per city/day, or pause after a same-direction loss cluster. This addresses the current adjacent-hour regime failure.
5. **Add an asymmetric-risk guard for expensive NO trades.** For rain and bucket markets, cap selected NO price or require a much larger calibrated EV margin when downside is 60–95¢ and upside is only 5–40¢.
6. **Recalibrate `_sigma` and band/rain models from settled shadow data.** Hourly temp σ is still too tight for decision-making, and the band/rain logic needs separate calibration rather than borrowing the same confidence framing.
7. **Backfill skipped high-EV outcomes.** Add a counterfactual audit table/script so "missed trades" can be evaluated by actual settlement, not just model EV.
8. **Fix/monitor stale unsettled shadow orders.** At minimum, dashboard should flag any `SHADOW_FILLED` row past `close_time + N hours`.
9. **Add a clean-calibration dashboard tile.** Show non-lookahead N, P/L, Brier, mean p vs empirical, and independent events separately from lookahead rows.

## Bottom line

The infrastructure is doing its job: scanning every ~10 minutes, preserving read-only production-shadow safety, enforcing event lockout, and recording skip reasons. The strategy is the problem. Current post-reset production-shadow performance is **−$4.69**, with terrible calibration and a negative clean sample. The bot should be treated as a data collector/model-debugging tool only until bias correction, adjacent-hour risk controls, expensive-NO constraints, and counterfactual skipped-trade audits are implemented and re-tested.

---

# Shadow-run observations

**Generated:** 2026-06-03 02:25 UTC
**Database:** Supabase project `weather-bot` (`xtttchcsmlzjsxcnrttb`), queried live via `supabase db query --linked`.
**Scope:** point-in-time report on the current post-reset production-shadow ledger in `shadow_snapshots`, `shadow_orders`, `scans`, and `runner_events`. Counts/open positions change as the Railway cron continues running.
**Supersedes:** the 2026-06-02 19:00 UTC report. This update adds ~7.5h and 6 new settled fills that completed a full 24h diurnal cycle for the first time post-reset — and that cycle changed the headline story.

## Context I used

Same handoff docs as before (`PROJECT_STATUS.md`, `plan.md`, `README.md`, `docs/deployment.md`, the 2026-05-30 shadow-gate design spec) plus the implementation in `shadow.py` / `probability.py` / `safety.py` / `storage.py` / `calibration.py` / `runner.py`.

Interpretation rules (unchanged):

- Shadow fills are simulated/read-only; no live orders are submitted.
- `status='SHADOW_FILLED' AND realized_pnl_cents IS NULL` = open/unsettled simulated fill; `SHADOW_SETTLED` with `realized_pnl_cents` = settled outcome.
- Side-aware win probability is `probability_yes` for `BUY_YES`, `1 - probability_yes` for `BUY_NO`.
- `lookahead_risk = 1` rows are same-day/elapsed contracts and are **not** clean go/no-go evidence.
- `result_value` is best-effort; `settlement_result` + realized P/L are authoritative.

## Headline status

The system is healthy and selective, but the extra 7.5h of settlements **eroded the apparent edge**: P/L fell from +214¢ to +195¢ even as cost basis more than doubled, win rate slipped to 37.5%, and the bot lost a tight cluster of three consecutive evening trades. The remaining profit is still entirely a midday-accuracy windfall, not edge.

| Metric | 19:00 UTC (prior) | 02:25 UTC (now) | Δ |
|---|---:|---:|---:|
| Shadow scans | 84 | **128** | +44 |
| Shadow snapshots | 2,771 | **4,405** | +1,634 |
| Shadow fills | 15 | **21** | +6 |
| Settled fills | 10 | **16** | +6 |
| Open fills | 5 | **5** | — |
| Settled win rate | 40.0% | **37.5%** (6/16) | ↓ |
| Settled P/L | +214¢ | **+195¢ / +$1.95** | ↓19¢ |
| Settled cost basis | 186¢ | **405¢** | +219¢ |
| Open exposure (incl. fee) | 375¢ | **334¢** | ↓ |
| Settled non-lookahead rows | 0 | **0** | — |

Key point: **all 16 settled fills are `lookahead_risk = 1`.** There is still **zero** clean (non-lookahead) settled shadow data. The two clean open positions from the prior report still have not settled. Any profitability claim remains unsupported.

## The big new finding: a clean diurnal forecast-bias pattern

For the first time post-reset, settlements now span a full 24h of NYC hourly temperature events. They reveal a sharp, repeatable structure that the earlier "cold-bias" story missed. Settled `KXTEMPNYCH`, in clock order:

| Hour (ET) | Side | `forecast − result` | Outcome | P/L |
|---:|---|---:|:--|---:|
| 02 | BUY_NO | −1.6 | loss | −2¢ |
| 03 | BUY_NO | −2.9 | loss | −5¢ |
| 04 | BUY_NO | −3.6 | loss | −9¢ |
| 05 | BUY_NO | −3.4 | loss | −7¢ |
| 06 | BUY_NO | −4.4 | loss | −12¢ |
| 07 | BUY_NO | −2.0 | loss | −7¢ |
| 09 | BUY_YES | +1.0 | **WIN** | +90¢ |
| 10 | BUY_YES | +0.1 | **WIN** | +51¢ |
| 11 | BUY_YES | +0.8 | **WIN** | +56¢ |
| 12 | BUY_YES | +1.1 | **WIN** | +59¢ |
| 15 | BUY_YES | +1.3 | **WIN** | +51¢ |
| 17 | BUY_YES | +2.4 | loss | −52¢ |
| 18 | BUY_YES | +2.5 | loss | −30¢ |
| 19 | BUY_YES | +2.6 | loss | −14¢ |
| 21 | BUY_NO | −0.3 | **WIN** | +66¢ |
| 22 | BUY_NO | −2.5 | loss | −40¢ |

Two facts jump out:

1. **The forecast error is diurnal.** Open-Meteo's lead-0 hourly forecast (vs the Kalshi settlement source) runs **too cold overnight** (hours 02–07, −1.6 to −4.4°F), **accurate midday** (hours 09–15, −0.1 to +1.3°F), **too warm in the evening cooling** (hours 17–19, +2.4 to +2.6°F), then swings cold again late (hour 22, −2.5°F). This is a classic diurnal lag — the forecast under-shoots overnight lows and over-shoots the evening cool-down.
2. **Outcome is governed almost entirely by the magnitude of that error vs the 1°F strike spacing.** Every settled bet with `|forecast − result| ≤ 1.3°F` **won**; every bet with `|forecast − result| ≥ 2.0°F` **lost**. There are no exceptions in the 16-row sample. With realized hourly MAE ≈ **2.03°F** against 1°F strikes, the model only has edge inside the narrow midday window where its forecast happens to be accurate.

The bot's trade *direction* tracks the bias, so the bias pushes it onto the losing side at both tails: a too-cold forecast → BUY_NO → warmer reality beats it; a too-warm forecast → BUY_YES → cooler reality beats it. The by-side aggregates confirm this anti-correlation:

| Series | Side | Settled | Wins | P/L | Avg fill | Mean `fcst − result` |
|---|---|---:|---:|---:|---:|---:|
| KXTEMPNYCH | BUY_NO | 8 | 1 | −16¢ | 13.3¢ | **−2.59°F** (too cold) |
| KXTEMPNYCH | BUY_YES | 8 | 5 | +211¢ | 34.4¢ | **+1.48°F** (too warm) |

### Where the +195¢ actually comes from

| Window | Hours | Net P/L |
|---|---|---:|
| Overnight NO cluster | 02–07 | **−42¢** |
| Midday YES window (accurate forecast) | 09–15 | **+307¢** |
| Evening YES cluster (warm-biased) | 17–19 | **−96¢** |
| Late-evening NO | 21–22 | **+26¢** |
| **Total** | | **+195¢** |

The entire profit is the +307¢ midday windfall (five YES wins where the forecast was within ~1°F). Every tail window, where the diurnal error exceeds the strike spacing, is a net loss. Strip the midday accuracy and the strategy is negative. This is the operational definition of "no edge on hourly temp outside the accurate window."

## The most important new mistake: consecutive-hour correlated losses

The old correlated-ladder bug (many strikes, one event) is gone — confirmed below. But a *new* correlation has now materialized in the data, and it's exactly the consecutive-hour regime risk flagged as recommendation #6 in the prior report:

- **Evening:** hours 17, 18, 19 — **three consecutive `BUY_YES` bets, all lost, −96¢**, all driven by the *same* +2.5°F warm forecast bias.
- **Overnight:** hours 02–07 — **six consecutive `BUY_NO` bets, all lost, −42¢**, all driven by the *same* cold bias.

The per-event lockout (`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT`, `MAX_CONTRACTS_PER_EVENT=1`) correctly limits each hour to one strike, but it does **nothing** across adjacent hours. When a forecast/source-basis regime error persists for several hours — which is the norm, not the exception, because temperature forecast errors are autocorrelated within a day — the bot takes the same losing side again and again. This is a milder version of the original −74¢ catastrophe, but it is the same failure shape and it is now real in the post-reset ledger.

## Calibration signal

Still weak, and slightly worse than the prior snapshot now that the high-conviction evening/overnight losses are in:

- Settled rows: **16** (all `lookahead_risk=1`); independent events: 16.
- Mean predicted win probability: **0.646**; empirical win rate: **0.375**.
- Brier score: **0.339** (worse than a naive 0.5 baseline, which would be 0.25).
- Log loss: **0.889**.
- Forecast MAE: **2.03°F**; mean forecast bias (`forecast − result`): **−0.56°F** overall (the diurnal swings partly cancel, which is why a single global offset would *not* fix this — it must be per-hour).

Reliability bins — the overconfidence is concentrated exactly where the bot bets biggest:

| Predicted bin | N | Mean predicted | Empirical win rate | P/L |
|---|---:|---:|---:|---:|
| 0.50–0.60 | 6 | 0.582 | 0.667 | +247¢ |
| 0.60–0.70 | 6 | 0.644 | 0.333 | +16¢ |
| 0.70–0.80 | 4 | 0.744 | **0.000** | **−68¢** |

The model's *highest*-conviction bets (p ≥ 0.70) went **0-for-4**. Confidence is anti-correlated with accuracy in this sample — a textbook overconfident-σ signature, even after the 2026-05-28 σ widening. Honest read: **not enough clean settled data, and what we have is poorly calibrated.**

## Current open shadow positions (5)

| ID | Ticker | Side | p_win | Cost incl. fee | Close (UTC) | Note |
|---:|---|---|---:|---:|---|---|
| 21 | `KXTEMPNYCH-26JUN0223-T67.99` | BUY_NO | 0.768 | 8¢ | 06-03 03:00 | Same-day/lookahead; forecast 64.7°F — watch the cold-bias risk |
| 3 | `KXRAINNYC-26JUN02-T0` | BUY_NO | 0.980 | 95¢ | 06-03 03:59 | Same-day/lookahead |
| 2 | `KXHIGHCHI-26JUN02-B74.5` | BUY_NO | 0.843 | 62¢ | 06-03 05:59 | Same-day/lookahead |
| 14 | `KXRAINNYC-26JUN03-T0` | BUY_NO | 0.990 | 96¢ | 06-04 03:59 | **Non-lookahead** (clean) |
| 12 | `KXHIGHCHI-26JUN03-B82.5` | BUY_NO | 0.868 | 73¢ | 06-04 05:59 | **Non-lookahead** (clean) |

The same two clean non-lookahead candidates (`KXRAINNYC-26JUN03`, `KXHIGHCHI-26JUN03`) are still pending — they're the first rows that will produce go/no-go-quality data. ID 15 from the prior report has since settled (YES, +51¢); the new open ID 21 is another overnight NYC `BUY_NO` whose 64.7°F forecast is precisely the cold-biased overnight pattern that lost six times today — flag for review when it settles (~03:00 UTC).

## Runner / infrastructure health

Cloud runner is healthy; one transient upstream blip:

- Latest scan: `2026-06-03 02:20:18 UTC`; latest runner event: `02:20:32 UTC`.
- Scans in last 24h: **128**; average gap **10.05 min**; max gap **16.09 min**; gaps > 20 min: **0**.
- Latest scan: `scan_id=128 shadow_markets=188 shadow_snapshots=38 shadow_fills=0 shadow_market_errors=0 shadow_pnl_checked=5 shadow_pnl_settled=0`.
- Runner errors in last 24h: **1** — a transient `502 Bad Gateway` from `external-api.kalshi.com` for series `KXTEMPMIAH` at 21:50 UTC. Per-market error isolation (`shadow_market_errors`) handled it: the scan continued and every subsequent scan reports 0 market errors. Upstream flakiness, not a bot bug; no action needed.
- No past-close position is stuck unsettled right now (the prior report's ID 15 latency resolved on its own). Settlement parsing in `Store.settle_shadow_orders_for_market` looks fine.

## Scan / skip behavior

| Reason | Snapshots | % |
|---|---:|---:|
| `probability_below_min_trade_probability` | 3,074 | 69.78% |
| `not_best_strike_in_event` | 595 | 13.51% |
| `production_insufficient_fee_adjusted_edge` | 215 | 4.88% |
| `production_event_already_traded` | 164 | 3.72% |
| `no_executable_production_liquidity` | 127 | 2.88% |
| `forecast_uncertainty_exceeds_strike_spacing` | 118 | 2.68% |
| `production_cooldown_same_market_side` | 91 | 2.07% |
| filled shadow order | 21 | 0.48% |

Distribution is stable vs the prior report and consistent with good safety behavior: the 0.55 probability floor blocks ~70%, best-strike-per-event and the across-scan event lockout are clearly active, and only 21 of 4,405 snapshots became fills (0.48% — highly selective).

## Regression checks (known failure modes)

Both prior catastrophic patterns remain absent:

1. **Correlated-ladder over-betting:** no `event_ticker` has more than one shadow order. `BEST_STRIKE_PER_EVENT` + `DISALLOW_MULTIPLE_POSITIONS_PER_EVENT` are working.
2. **Low-confidence tail bets:** **0** filled orders have side-aware `p_win < 0.55`. `MIN_TRADE_PROBABILITY=0.55` is working.

The *new* correlation (consecutive-hour, same-direction across adjacent events — §"most important new mistake") is **not** covered by either of these guards and is currently uncontrolled.

## What we can do better (prioritized)

1. **Build the per-hour diurnal bias correction — highest-value model fix, now strongly evidenced.** The forecast error has clear time-of-day structure (cold overnight, accurate midday, warm evening). A per-station/per-hour rolling `forecast − result` table, subtracted from the forecast before `estimate_probability`, would have suppressed or flipped most of today's losing bets. Note the global bias is only −0.56°F because the tails cancel — a single offset is useless; it **must** be keyed on (station, variable, hour). This is the natural successor to the still-open "forecast bias correction per station/variable/hour" task and the data to fit it now exists.
2. **Add a consecutive-hour / per-day directional cap.** The event lockout doesn't stop the dominant new loss mode. Add a per-city/day same-direction limit (e.g. max N hourly bets in the same direction per city per day) and/or a cooldown after a same-direction loss, so one persistent regime error can't compound across 3–6 adjacent hours (−96¢ and −42¢ today).
3. **Treat "forecast MAE ≥ strike spacing" as a hard no-trade, not a soft EV input.** Empirically the win/loss boundary today sat right at ~1.5–2°F of forecast error vs 1°F strikes. Outside the midday accuracy window the hourly NYC temp market is noise. Options: restrict hourly temp trading to the accurate hours, require a multi-strike conviction cushion, or simply let the conservative gate (`FORECAST_UNCERTAINTY_GATE_RATIO=1.0`) do its job once the relaxed shadow experiment ends — remember the relaxed `SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO=6.0` is *why* these hourly fills exist; they are calibration data, not edge.
4. **Recalibrate σ wider for hourly point-temp after 2026-06-06.** Predicted 0.646 vs empirical 0.375, and the p ≥ 0.70 bin went 0/4 (−68¢): the widened σ (4.5°F) is still too tight for lead-0 hourly. Refit `probability._sigma` from these realized errors when the gate auto-reverts and rerun `kalshi-weather-calib --source shadow`.
5. **Ship the clean-calibration tile and wait for non-lookahead settlements.** Settled non-lookahead count is still **0**. Add a dashboard tile showing settled non-lookahead N, P/L, Brier, predicted-vs-empirical, and independent events; until the two clean opens (`KXHIGHCHI-26JUN03`, `KXRAINNYC-26JUN03`) settle, no go/no-go claim is valid.
6. **Keep live trading disabled.** +$1.95 over 16 lookahead-contaminated fills at 37.5% win rate and Brier 0.34 is not edge — it's a small-sample midday windfall partly offset by correlated tail losses.

## Bottom line

The shadow infrastructure is healthy, selective, and free of the old catastrophic safety regressions. But the extra 7.5h of settlement data is a step *backward* for the edge thesis, not forward: P/L slipped to +195¢ on a doubled cost basis, win rate fell to 37.5%, calibration stayed poor (Brier 0.34, high-conviction bin 0/4), and a full diurnal cycle exposed the real mechanism — a **time-of-day forecast bias** (cold overnight, warm evening) whose magnitude routinely exceeds the 1°F strike spacing, with the bot's trade direction landing on the losing side at both tails. The single most actionable improvement is a **per-hour forecast bias correction**, paired with a **consecutive-hour directional cap** to stop one regime error from compounding across adjacent hourly events. Clean non-lookahead settlements are still required before any stronger claim. Live trading stays off.
