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
- A setup whose TP1 has already traded before entry is stale; it must not be
  presented as a fresh executable order with the old target ladder.
- MARKET fills use the next available candle open in the historical simulator.
- Intrabar ambiguity is resolved conservatively: stop-first where OHLC cannot
  establish event order; partial exits advance only on subsequent candles.
- Fees/slippage must be applied exactly once per simulated round trip. Existing
  fee regression coverage verifies the configured round-trip fee in the
  non-partial path; partial-exit and live-journal parity still require a
  dedicated end-to-end reconciliation.

## Remaining validation before live use

- Replay identical timestamped specialist inputs through live analysis and
  backtest; current OHLCV replay cannot recreate historical order book and
  actual taker flow when the provider did not archive them.
- Complete a frozen-parameter walk-forward and out-of-sample evaluation with
  per-symbol, direction, setup and regime statistics.
- Reconcile fee, spread and slippage accounting across risk sizing, backtest,
  and signal outcome journal, including partial exits.
- Test stale-cache restoration, signal expiry, restart recovery, and all legacy
  exchange-order execution paths.
- Measure each specialist motor with ablation tests; retain only evidence that
  improves entry quality or out-of-sample outcomes.

## Safety

Atlas remains analysis-only. Do not enable exchange order placement through
environment variables, legacy credentials, or compatibility modules.
