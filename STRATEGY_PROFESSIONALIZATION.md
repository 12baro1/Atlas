# Seven Strategy Professionalization Contract

Status: implementation specification. This document is not a claim that the strategies are already production-grade.

## Non-negotiable architecture
- Preserve all seven independent engines: trend pullback, volatility breakout, mean reversion, liquidation cascade, order-flow momentum, relative strength, and existing SMC.
- Each engine returns a typed candidate with direction, entry type, entry, invalidation stop, structural targets, costs, data quality, timestamp, and explicit rejection reasons.
- Evaluate against one immutable, timestamp-aligned market snapshot. Never mix candles or live snapshots from different times.
- The selector must not treat hand-tuned strength as win probability. Select only candidates passing hard risk, data-quality, and execution checks.
- Preserve existing SMC behavior as strategy seven. No silent gate weakening or mixing price levels between engines.
- No exchange order placement.

## Engine requirements

### 1. Trend Following + Pullback
- Multi-timeframe structure/trend agreement (4H/1H), not EMA crossover alone.
- Quantify trend quality (ADX/efficiency/slope), pullback depth, impulse quality, and reclaim confirmation.
- Place stop beyond actual swing/structure invalidation with ATR buffer.
- Target opposing liquidity/market structure; reject insufficient room after costs.

### 2. Volatility Breakout
- Detect volatility compression before expansion (ATR percentile/Bollinger bandwidth).
- Require closed-candle breakout, relative volume, displacement, and non-exhausted entry.
- Separate breakout continuation from breakout-retest entries.
- Stop beyond retest/failed-breakout invalidation; target measured move and external liquidity.

### 3. Mean Reversion
- Operate only in statistically identified range regimes.
- Use VWAP/deviation, volatility bands, RSI as confirmation only, and nearby liquidity sweep/reclaim.
- Reject trend-day countertrend entries and entries whose mean/target is already crossed.
- Stop beyond range extreme/sweep invalidation; target VWAP/equilibrium and opposing range liquidity.

### 4. Liquidation Cascade
- Never label OI contraction as a liquidation feed.
- Prefer timestamped exchange liquidation events where supported; otherwise mark proxy-only and lower data confidence.
- Combine OI change, price displacement, funding, taker delta, and post-sweep reclaim/continuation.
- Distinguish long liquidation cascades from short squeezes; OI contraction alone cannot infer side.

### 5. Order Flow Momentum
- Normalize book imbalance by depth/notional; reject stale, crossed, or abnormal books.
- Use signed taker volume, rolling CVD, delta divergence, absorption proxies, and multi-window confirmation where available.
- A single order-book snapshot is insufficient evidence of sustained momentum.
- Report unavailable data instead of fabricating features.

### 6. Relative Strength
- Compare against BTC, ETH, and a configurable liquid peer basket with identical timestamps.
- Use rolling relative returns, beta-adjusted residual strength, correlation regime, and breadth where available.
- Require absolute trend confirmation; relative strength alone cannot force a trade against strong adverse market regime.
- Never use BTC as its own benchmark; handle missing peer data safely.

### 7. Existing SMC
- Preserve CHoCH/BOS, liquidity sweep, EQH/EQL, FVG, OTE, POI, and 15m confirmation logic.
- Keep weekly/daily range context and 4H structure as higher-timeframe context.
- Targets remain structural liquidity levels, not fixed R multiples.
- Add diagnostics/tests without changing existing decision behavior unless separately reviewed.

## Shared professional infrastructure

### Market data and integrity
- Typed snapshot records exchange, symbol, timeframe, candle-close timestamps, ticker/book timestamps, trade window, OI/funding timestamps, and source quality.
- Enforce no-lookahead: only fully closed candles drive historical signals; live ticker/book/trades must be timestamp-fresh.
- Align timeframe bars and benchmark series; detect gaps, duplicates, stale feeds, impossible OHLC, and API fallback.
- Cache only immutable validated data and record provider failures per feature.

### Execution and risk model
- Model maker/taker fees, spread, slippage, funding, latency, partial fills, limit non-fills, and conservative stop/target ordering.
- Use exchange market metadata for tick size, lot size, minimum quantity/notional, and precision.
- Stops are structural and volatility-aware; never widen risk silently to force a candidate.
- Compute net R after modeled costs. Reject impossible or negative net expectancy setups.
- Separate signal generation, execution eligibility, and position sizing.

### Selection and learning
- Persist every candidate, rejection, selection, and eventual outcome with strategy ID and immutable setup ID.
- Keep strategy-specific outcomes separate; never mix SMC results with experimental engines.
- Use minimum sample gates, shrinkage/Bayesian estimates, and confidence intervals; small samples fall back to neutral priors.
- Select using out-of-sample net expectancy, drawdown, PF, sample size, stability, and regime match—not raw hand-tuned scores.
- Add regime-change decay/cooldown; prevent a recent single win from dominating selection.
- If no strategy has validated positive OOS expectancy, report no validated edge rather than inventing a winner.

### Backtesting and validation
- Deterministic event-driven runner replays synchronized historical snapshots.
- Include warmup, realistic fills, fees, spread/slippage, funding, limit non-fill, partial fill, and conservative same-bar stop/target resolution.
- Use chronological train/validation/test splits and walk-forward evaluation; never tune on final test.
- Report per strategy/regime: trades, exposure, win rate, average win/loss R, expectancy, PF, max DD, Sharpe/Sortino, turnover, costs, and confidence intervals.
- Add benchmark comparisons and parameter sensitivity/stability checks.
- Add unit, integration, data-quality, leakage, and deterministic replay tests.

## Acceptance gates
1. All seven engines have independent unit and synthetic edge-case tests.
2. Snapshot timestamps and no-lookahead invariants are tested.
3. Each engine has reproducible historical backtests with realistic costs.
4. Walk-forward and untouched out-of-sample results exist per engine and regime.
5. Selector decisions are reproducible from persisted candidate/performance records.
6. No engine is promoted based only on in-sample win rate or hand-authored score.
7. Existing SMC regression suite stays green and its signal behavior is preserved.
8. README/TUI accurately label experimental, proxy-only, unavailable, and validated components.

## Delivery sequence
1. Snapshot/data contracts and test fixtures.
2. Execution simulator and deterministic backtest runner.
3. Upgrade engines independently, one at a time.
4. Strategy outcome journal and walk-forward performance model.
5. Replace selector and add TUI diagnostics.
6. Full regression, leakage audit, and out-of-sample report.

Promotion requires passing the same acceptance gates for every strategy. No profitability guarantee is implied.

## Follow-up implementation tranche (PR #115)

Implemented on top of the professionalization branch:

- Anchored expanding-window walk-forward reporting with five sequential test folds per strategy. Each fold reports prior-window training metrics and its next untouched test window. This is validation, not automated parameter tuning.
- Timestamped historical Bybit OI and funding loaders with pagination, deduplication, time-window filtering, and explicit unsupported/unavailable states. No current-value substitution is allowed in replay.
- Funding settlement cash flow is applied to simulated trades according to position direction. A positive funding rate is a debit to longs and a credit to shorts; net cost R may therefore be negative when funding credits exceed modeled execution costs.
- Outcome persistence is blocked when historical funding is unavailable, so incomplete cost samples cannot enter the strategy performance gate.
- Live order-book and recent-trade snapshots are archived locally as JSONL and replayed only when their timestamps precede the historical decision and meet freshness limits. This archive starts collecting from deployment onward; it cannot recreate past order books.
- Historical liquidation analysis can use timestamped OI/funding plus archived trade flow, but remains a proxy and is not a true liquidation-event feed.

The exchange's historical order-book archive is not exposed by the current CCXT/Bybit path. Therefore complete historical book replay remains data-limited until an external historical L2 provider or a sufficiently long local archive is available. Fees, spread, and slippage remain assumptions. Unit tests were added; merge still requires a completed passing CI run and a local full-suite run.
