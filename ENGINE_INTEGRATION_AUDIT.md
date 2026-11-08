# Atlas engine integration audit

This document records the boundaries of the integrated engine work. A green test
suite is not evidence of a profitable strategy.

## Decision and motor responsibilities

- Primary weekly/daily/4H structure, valid POI, stop geometry, structural targets,
  and positive cost-adjusted RR remain execution-critical.
- Specialist evidence (SMT, Unicorn, CISD, institutional flow, Volume Profile,
  liquidity sweep, market phase/regime, correlation and order-book pressure)
  must influence the common entry, order type, warning or confidence diagnostics.
  It must not become a duplicate directional vote or an unrelated hard veto.
- Macro-news protection and duplicate-position cooldown remain hard operational
  gates. Correlation conflicts and order-book pressure are retained as warnings
  and entry-placement evidence.
- Missing or stale market data must fail closed. Missing historical order-book,
  taker-flow, OI or funding data must be labelled unavailable; OHLCV proxies must
  never be presented as actual historical order flow.

## Execution and backtest invariants

- LIMIT orders are not filled unless a later candle touches the limit.
- A MARKET setup whose TP1 has already traded is stale and must not be chased.
- A pending LIMIT may remain actionable after its original TP1 trades only when
  all crossed targets are removed and the remaining structural TP ladder is
  rebuilt; no remaining target means the LIMIT is invalid.
- MARKET fills use the next available candle open in the historical simulator.
- Intrabar ambiguity is resolved conservatively: stop-first where OHLC cannot
  establish event order; partial exits advance only on subsequent candles.
- Configured round-trip fee, spread proxy and slippage proxy are applied once
  to backtest net R. Live signal outcomes persist the RiskEngine's captured
  fee rate and absolute spread/slippage buffers and deduct them once after
  partial-exit realization. OHLCV replay still uses percentage proxies rather
  than historical order-book spread or exact market impact.

## Remaining validation before live use

- Replay identical timestamped specialist inputs through live analysis and
  backtest; current OHLCV replay cannot recreate historical order book and
  actual taker flow when the provider did not archive them.
- Complete a frozen-parameter walk-forward and out-of-sample evaluation with
  per-symbol, direction, setup and regime statistics.
- Validate modeled fee/spread/slippage parity against exchange instrument tick
  sizes and actual fills; historical OHLCV cannot establish exact market impact.
- Test stale-cache restoration, signal expiry, restart recovery, and all legacy
  exchange-order execution paths.
- Measure each specialist motor with ablation tests; retain only evidence that
  improves entry quality or out-of-sample outcomes.

## Safety

Atlas remains analysis-only. Do not enable exchange order placement through
environment variables, legacy credentials, or compatibility modules.


## Additional regression coverage added in this integration branch

- Live OHLCV ingestion now removes the still-forming final candle and rejects
  non-finite, malformed, duplicate, out-of-order, or impossible OHLC rows.
- Backtest tests assert fee, spread and slippage proxies are deducted once.
- Signal outcome tests assert captured RiskEngine fee/spread/slippage buffers
  are deducted once after partial-exit realization.
- LIMIT repricing tests exclude signal-candle-crossed targets and refuse to
  fabricate a replacement target when no structural objective remains.
- Trade-journal close transitions are idempotent: a duplicate close event is
  ignored and cannot overwrite the first exit or double-count performance.
