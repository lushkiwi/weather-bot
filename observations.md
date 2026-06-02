# Shadow-run observations

**Generated:** 2026-06-02 19:00 UTC  
**Database:** Supabase project `weather-bot` (`xtttchcsmlzjsxcnrttb`)  
**Scope:** point-in-time report on the current post-reset production-shadow ledger in `shadow_snapshots`, `shadow_orders`, `scans`, and `runner_events`. Counts/open positions may change as the Railway cron continues running.

## Context I used

I reviewed the project handoff docs and the shadow implementation before querying:

- `PROJECT_STATUS.md` — current model-quality caveats, post-reset status, risk fixes, and active shadow-gate experiment.
- `plan.md` — phase boundaries and live-trading preconditions.
- `README.md` — shadow-tracking semantics, safety limits, calibration command, and dashboard meaning.
- `docs/deployment.md` — Railway + Supabase shadow-only deployment.
- `docs/superpowers/specs/2026-05-30-shadow-gate-experiment-design.md` — why the shadow gate is temporarily relaxed.
- Code paths summarized by subagents: `shadow.py`, `probability.py`, `safety.py`, `storage.py`, `calibration.py`, `runner.py`.

Important interpretation rules:

- Shadow fills are simulated/read-only; no live orders are being submitted.
- `shadow_orders.status = 'SHADOW_FILLED' AND realized_pnl_cents IS NULL` means open/unsettled simulated fill.
- `SHADOW_SETTLED` rows with `realized_pnl_cents` are settled simulated outcomes.
- For model calibration, side-aware win probability is `probability_yes` for `BUY_YES` and `1 - probability_yes` for `BUY_NO`.
- `lookahead_risk = 1` rows should not be treated as clean go/no-go evidence.

## Headline status

The bot is running and writing data correctly, but the current profit number is too small and too contaminated by same-day/lookahead rows to prove edge.

- Shadow scans: **84** since `2026-06-02 05:04 UTC`.
- Shadow snapshots: **2,771**.
- Shadow fills: **15** total.
- Settled fills: **10**.
- Open fills: **5**.
- Settled win rate: **4 / 10 = 40.0%**.
- Settled P/L: **+214¢ / +$2.14**.
- Settled cost basis: **186¢**, so observed ROI is high, but on a tiny and non-clean sample.
- Open exposure: **367¢ / $3.67** before fees; **375¢ / $3.75** including recorded fees.
- All 10 settled fills have `lookahead_risk = 1`; there are currently **0 settled non-lookahead fills**.

The positive P/L is mostly a payoff-shape artifact: one cheap 9¢ BUY_YES winner made +90¢, and four BUY_YES winners more than offset six small BUY_NO losses. The win rate and calibration are not strong. Also note the project’s documented caveat: `result_value` is best-effort/possibly approximate; `settlement_result` and realized P/L are the authoritative outcomes.

## Runner / infrastructure health

The cloud runner appears healthy.

- Latest scan at query time: `2026-06-02 19:00:22 UTC`.
- Latest runner event at query time: `2026-06-02 19:00:39 UTC`.
- Scans in the last 24h: **84**.
- Average scan gap: **10.07 minutes**.
- Maximum scan gap: **16.09 minutes**.
- Gaps over 20 minutes: **0**.
- Runner errors in last 24h: **0**.
- Recent runner messages show `shadow_only=True`, `execute_demo=False`, `production_shadow=True`, and `shadow_market_errors=0`.

This suggests the Railway cron + Supabase write path is working.

## Current open shadow positions

| ID | Ticker | Side | p_win | Cost incl. fee | Target | Close | Note |
|---:|---|---|---:|---:|---|---|---|
| 15 | `KXTEMPNYCH-26JUN0215-T74.99` | BUY_YES | 0.696 | 49¢ | NYC hourly temp, 3pm EDT, Jun 2 | 2026-06-02 19:00 UTC | Past close at query time, settlement pending |
| 3 | `KXRAINNYC-26JUN02-T0` | BUY_NO | 0.980 | 95¢ | NYC rain, Jun 2 | 2026-06-03 03:59 UTC | Same-day/lookahead risk |
| 2 | `KXHIGHCHI-26JUN02-B74.5` | BUY_NO | 0.843 | 62¢ | Chicago high 74–75°, Jun 2 | 2026-06-03 05:59 UTC | Same-day/lookahead risk |
| 14 | `KXRAINNYC-26JUN03-T0` | BUY_NO | 0.990 | 96¢ | NYC rain, Jun 3 | 2026-06-04 03:59 UTC | Non-lookahead |
| 12 | `KXHIGHCHI-26JUN03-B82.5` | BUY_NO | 0.868 | 73¢ | Chicago high 82–83°, Jun 3 | 2026-06-04 05:59 UTC | Non-lookahead |

Two open positions are clean non-lookahead candidates (`KXRAINNYC-26JUN03`, `KXHIGHCHI-26JUN03`), but they have not settled yet.

## Settled-trade breakdown

All settled rows are `KXTEMPNYCH` same-day hourly temperature fills and all have `lookahead_risk=1`.

By side:

| Series | Side | Settled | Wins | Win rate | P/L | Mean p_win | Avg fill |
|---|---|---:|---:|---:|---:|---:|---:|
| KXTEMPNYCH | BUY_NO | 6 | 0 | 0% | -42¢ | 0.678 | 6¢ |
| KXTEMPNYCH | BUY_YES | 4 | 4 | 100% | +256¢ | 0.589 | 34.25¢ |

Worst settled mistakes:

| Ticker | Side | p_win | Forecast | Result value | Settlement | P/L |
|---|---|---:|---:|---:|---|---:|
| `KXTEMPNYCH-26JUN0206-T51.99` | BUY_NO | 0.774 | 48.6°F | 53°F | YES | -12¢ |
| `KXTEMPNYCH-26JUN0204-T51.99` | BUY_NO | 0.718 | 49.4°F | 53°F | YES | -9¢ |
| `KXTEMPNYCH-26JUN0207-T52.99` | BUY_NO | 0.587 | 52.0°F | 54°F | YES | -7¢ |
| `KXTEMPNYCH-26JUN0205-T51.99` | BUY_NO | 0.774 | 48.6°F | 52°F | YES | -7¢ |
| `KXTEMPNYCH-26JUN0203-T51.99` | BUY_NO | 0.663 | 50.1°F | 53°F | YES | -5¢ |
| `KXTEMPNYCH-26JUN0202-T51.99` | BUY_NO | 0.552 | 51.4°F | 53°F | YES | -2¢ |

The losses are small because those were cheap NO contracts, but the pattern is important: the model repeatedly thought “below this low threshold” was likely, while the settlement source came in warmer than forecast.

## Calibration signal

Including all settled rows, calibration is weak:

- Settled rows: **10**.
- Independent events: **10**.
- Mean predicted win probability: **0.6423**.
- Empirical win rate: **0.4000**.
- Brier score: **0.3480**.
- Log loss: **0.9136**.
- Forecast MAE: **2.09°F**.
- Forecast bias (`forecast - result`): **-1.49°F** overall.

By side, the early BUY_NO losses show the real issue:

- BUY_NO rows: average forecast error **-2.98°F** (`forecast - result`), MAE **2.98°F**.
- BUY_YES rows: average forecast error **+0.75°F**, MAE **0.75°F**.

Reliability bins were also not reassuring:

| Predicted bin | N | Mean predicted | Empirical win rate | P/L |
|---|---:|---:|---:|---:|
| 0.50–0.60 | 6 | 0.582 | 0.667 | +247¢ |
| 0.60–0.70 | 1 | 0.663 | 0.000 | -5¢ |
| 0.70–0.80 | 3 | 0.755 | 0.000 | -28¢ |

Caveat: because all settled rows are `lookahead_risk=1`, this is not a clean calibration sample. Excluding lookahead rows leaves no settled rows yet, so the honest model-quality answer is: **not enough clean settled shadow data yet**.

## Scan / skip behavior

Overall skip distribution from `shadow_snapshots`:

| Reason | Snapshots | Percent |
|---|---:|---:|
| `probability_below_min_trade_probability` | 1,907 | 68.82% |
| `not_best_strike_in_event` | 449 | 16.20% |
| `production_insufficient_fee_adjusted_edge` | 120 | 4.33% |
| `production_cooldown_same_market_side` | 77 | 2.78% |
| `production_event_already_traded` | 73 | 2.63% |
| `no_executable_production_liquidity` | 68 | 2.45% |
| `forecast_uncertainty_exceeds_strike_spacing` | 62 | 2.24% |
| filled shadow order | 15 | 0.54% |

This is mostly good safety behavior:

- The probability floor is doing a lot of work, blocking nearly 69% of evaluated snapshots.
- `not_best_strike_in_event` confirms best-strike-per-event is filtering ladders.
- `production_event_already_traded` confirms the across-scan event lockout is active.
- Only 15 of 2,771 snapshots became fills, so the bot is selective.

Series-specific notes:

These rates are over persisted shadow evaluations/snapshots, not every raw Kalshi market encountered by the runner.

- `KXTEMPNYCH`: 11 fills out of 1,949 snapshots (~0.56%). Main skip reason is `probability_below_min_trade_probability` (77.53%).
- `KXHIGHCHI`: 2 fills out of 708 snapshots (~0.28%). Main skip reason is `probability_below_min_trade_probability` (53.39%), with some uncertainty-gate skips (8.76%).
- `KXRAINNYC`: 2 fills out of 114 snapshots (~1.75%). Main skip reason is `production_insufficient_fee_adjusted_edge` (75.44%).

## Checks for regressions in known failure modes

I checked two major prior failure modes:

1. **Correlated-ladder over-betting regression:** no `event_ticker` currently has more than one shadow order. This indicates `BEST_STRIKE_PER_EVENT` plus `DISALLOW_MULTIPLE_POSITIONS_PER_EVENT` are working.
2. **Low-confidence tail-bet regression:** no filled shadow order has side-aware `p_win < 0.55`. This indicates `MIN_TRADE_PROBABILITY=0.55` is working.

So the earlier catastrophic failure mode (stacking many strikes in the same event) has not reappeared in the current Supabase ledger.

## Mistakes and likely causes

### 1. The early NYC BUY_NO trades were systematically wrong

The bot bought NO on low NYC hourly thresholds (`T51.99`, `T52.99`) from 2am–7am EDT. All six settled NO trades lost.

Likely cause: Open-Meteo forecasts were too cold relative to the Kalshi settlement source. For those six BUY_NO losses, `forecast - result` averaged **-2.98°F**. With 1°F strike spacing, this is a large miss. Even widened sigma did not prevent the model from assigning 0.66–0.77 win probabilities to several losing NOs.

This matches the project’s known root cause: forecast/source basis error plus uncalibrated probabilities can turn weather noise into fake EV.

### 2. Current positive P/L is not reliable evidence of edge

The +214¢ settled P/L is driven by four BUY_YES wins, including one 9¢ contract that paid +90¢. That is encouraging operationally, but it is not enough to conclude the model is profitable because:

- only 10 settled fills exist;
- all 10 are same-day/lookahead-risk rows;
- win rate is only 40%;
- mean predicted win probability (64.2%) is far above empirical win rate (40.0%);
- Brier score is poor at 0.348;
- there are 0 settled non-lookahead rows.

### 3. The shadow tracker is still recording same-day/lookahead-risk hourly fills

The ledger correctly flags these rows with `lookahead_risk=1`, but the shadow tracker still records simulated fills on them. That is acceptable for plumbing and exploratory data, but these rows should not be used as go/no-go proof.

Potential problem: same-day weather forecasts may partially include observations or nowcast data and still differ from Kalshi’s settlement station. This can create both leakage and source-basis distortion at the same time.

### 4. There may be regime-level correlation across consecutive hourly events

The event lockout prevents multiple strikes within one hourly event, but it does not prevent repeated same-direction exposure across adjacent hourly events. The early sequence shows six separate NYC hourly events all betting NO and all losing because the same cold forecast bias persisted across hours.

This is less severe than the old correlated-ladder bug, but it is still a risk pattern: a station/forecast regime error can defeat many consecutive hourly events even when each event has only one strike.

### 5. Settlement latency is normal but worth watching

Position ID 15 (`KXTEMPNYCH-26JUN0215-T74.99`) was past close at query time and still unsettled. The latest runner checked 5 open positions and settled 0. That is not necessarily a bug; Kalshi may not have posted the result yet. If it remains open for multiple scans after result publication, inspect result parsing in `Store.settle_shadow_orders_for_market`.

## Recommendations

1. **Do not infer live-trading readiness from the current +$2.14.** The sample is tiny and all settled rows are lookahead-risk.
2. **Wait for the two non-lookahead open positions to settle**, then rerun calibration excluding lookahead rows.
3. **Continue the bounded shadow-gate experiment only as data collection.** The relaxed gate is doing its job by letting temperature data through, but it should not be interpreted as a trading edge. Per the design, it auto-reverts on/after `2026-06-06`; rerun calibration after enough non-lookahead fills settle.
4. **Add/report a clean calibration tile:** settled non-lookahead count, P/L, Brier, mean predicted vs empirical, and independent events. Right now that count is 0.
5. **Consider a station/hour bias monitor**: for each series/hour, track `forecast_value - result_value`; the current BUY_NO losses show a clear cold-bias pattern.
6. **Consider a broader regime cap for hourly ladders** if the same city has repeated same-direction fills across adjacent hours. Event-level lockout is working, but consecutive-hour forecast bias can still create correlated losses.
7. **Keep live trading disabled.** The current evidence is operationally useful, not profitability proof.

## Bottom line

The shadow system itself is healthy, selective, and the major old safety regressions are not present. Performance is superficially positive (+214¢ settled), but model quality remains unproven and probably still fragile. The most important current mistake is repeated same-day NYC hourly BUY_NO exposure driven by a cold forecast/source-basis error. Clean non-lookahead shadow settlements are needed before making any stronger claim about edge.
