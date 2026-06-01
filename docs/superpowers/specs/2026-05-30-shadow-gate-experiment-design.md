# Bounded shadow-gate data-collection experiment

**Date:** 2026-05-30
**Status:** Implemented
**Scope:** `config.py`, `shadow.py`, `.env`, `.env.example`, project docs

## Problem

The forecast-uncertainty gate skips a temperature market when
`sigma >= FORECAST_UNCERTAINTY_GATE_RATIO * strike_spacing`
(`probability.forecast_resolves_strikes`). With the shipped runtime config
(`ratio = 1.0`, `default_strike_spacing_f = 1.0`) and the widened `_sigma`
(minimum 4.5 F point-temp / 5.0 F daily high), the pass condition `sigma < 1.0`
is unsatisfiable for **every** 1 F-spaced temperature ladder, at any lead time.

Measured impact over ~24h post-reset (2026-05-29 19:00 → 2026-05-30 19:52 UTC):

- 3,531 shadow evaluations → **94.7% skipped by `forecast_uncertainty_exceeds_strike_spacing`**, 3 fills.
- 100% of both temperature series gated out: `KXTEMPNYCH` (NYC hourly, 2,347 gated) and `KXHIGHCHI` (Chicago daily high, 996 gated).
- The only fills are `KXRAINNYC` (rain bypasses the gate via the `direct_probability` path).

This is a **deadlock**: `PROJECT_STATUS.md`'s stated near-term goal is to gather
production-shadow data to recalibrate `_sigma` and re-score
`kalshi-weather-calib --source shadow`, but the gate prevents the read-only
shadow tracker from ever recording a settled temperature outcome. The model
cannot earn its way out of the gate because the gate blocks the data that would
justify loosening it.

## Goal

Let the **read-only** shadow tracker collect settled temperature outcomes for a
bounded window, without weakening any control that prevents the original
−74¢ correlated-ladder loss, and without touching paper/demo/live paths.

## Decisions (user-approved 2026-05-30)

- **Scope:** shadow only. Paper/demo keep `forecast_uncertainty_gate_ratio = 1.0`.
- **Window:** 7 days, auto-reverts after `2026-06-06`.

## Design

### `config.py`

Two new shadow-scoped settings on `Settings`:

- `shadow_forecast_uncertainty_gate_ratio` (`SHADOW_FORECAST_UNCERTAINTY_GATE_RATIO`, default `6.0`).
  At 6.0, near-term temp ladders (sigma 4.5–6.0 vs 1 F spacing) pass; longer-lead / wider ones still gate out.
- `shadow_gate_experiment_until` (`SHADOW_GATE_EXPERIMENT_UNTIL`, default `2026-06-06`, ISO date).

Resolver `effective_shadow_gate_ratio(today=None)`:

- returns the relaxed ratio while `today <= until` (boundary inclusive);
- returns the conservative base `forecast_uncertainty_gate_ratio` once the window
  has passed, or if the date is empty/invalid.

The relaxed gate therefore cannot silently outlive its window.

### `shadow.py`

`_fails_uncertainty_gate` uses `self.settings.effective_shadow_gate_ratio()`
instead of the shared `forecast_uncertainty_gate_ratio`. `paper.py` is untouched.

### Controls deliberately NOT changed (the real safety)

`MIN_TRADE_PROBABILITY = 0.55`, the fee-adjusted EV gate, `BEST_STRIKE_PER_EVENT`,
`DISALLOW_MULTIPLE_POSITIONS_PER_EVENT`, `MAX_CONTRACTS_PER_EVENT = 1`, cooldown.
These are what actually stopped the 6-correlated-bet blowup. Even with the gate
relaxed, only one best strike per event reaches shadow, and it must still clear
EV + 0.55 conviction. The −74¢ failure mode stays blocked.

### Out of scope (YAGNI)

Data-driven strike spacing and demoting the gate to a soft tie-breaker — both are
model-design changes better made *after* this window produces calibration data.

## Verification

- `python -m compileall src` (repo verification gate) passes.
- Resolver assertions: relaxed in-window (incl. boundary day), conservative after,
  base ratio for empty/invalid date.
- Gate math: `forecast_resolves_strikes(4.5, 1.0, 6.0)` is True; `(4.5, 1.0, 1.0)` is False.
- Live `.env` load: paper ratio 1.0, `effective_shadow_gate_ratio()` 6.0 today, 1.0 on 2026-06-07.

## Follow-up (on/after 2026-06-06)

The gate auto-reverts to 1.0. Run `kalshi-weather-calib --source shadow` over the
post-experiment settled temperature fills to recompute `_sigma` / Brier before
deciding whether to keep, retune, or remove the gate.
