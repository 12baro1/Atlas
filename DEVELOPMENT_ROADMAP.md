# Atlas Engineering Roadmap

This is a living backlog, ordered by risk and user value. Keep it updated as work is merged; do not treat an item as complete without evidence in tests or reproducible reports.

## Release blockers / correctness

- [ ] Verify all market-data timestamps and higher-timeframe candle boundaries with deterministic tests, including exchange timezone and incomplete-candle edge cases.
- [ ] Audit every live analysis path for look-ahead bias, including cache restoration, correlation inputs, and all auxiliary SMC modules.
- [ ] Audit fee/slippage accounting end-to-end across backtest, signal outcome tracking, and manual-trade journal; prove that each cost is applied exactly once.
- [ ] Add malformed/missing/stale market-data tests and ensure the result is WAIT rather than a fabricated or overconfident setup.
- [ ] Confirm that no execution path can place exchange orders, even if legacy environment variables or credentials are present.

## Signal quality and honest evaluation

- [ ] Add a reproducible out-of-sample backtest command with frozen parameters, transaction costs, expectancy in R, profit factor, maximum drawdown, sample count, and per-symbol breakdown.
- [ ] Add walk-forward evaluation and a baseline comparison before changing signal thresholds.
- [ ] Calibrate heuristic score labels against observed outcomes; never label a score as a probability without statistical calibration.
- [ ] Separate statistics by symbol, direction, setup fingerprint, timeframe, and market regime when sample size permits.
- [ ] Audit dynamic RR/TP selection to ensure targets are market-structure based and not artificially fixed to a preferred RR.
- [ ] Verify signal expiry and prevent stale Telegram signals from appearing actionable after the market has moved.

## Local AI agent and terminal UX

- [ ] Make local inference the only default provider; fail visibly when offline and prohibit silent remote API fallback.
- [ ] Test Turkish intent parsing and multi-step tool chaining against a deterministic evaluation set.
- [ ] Harden tool dispatch with an explicit allowlist, schema validation, timeouts, and bounded retries.
- [ ] Add restart/recovery tests for TUI state, local conversation history, and atomic persistence after interrupted writes.
- [ ] Keep analysis details available in the TUI while maintaining a compact Telegram signal format.
- [ ] Add a simple local health/status screen for data provider, local model, Telegram, journal, and last successful analysis.

## Journal, learning, and reliability

- [ ] Verify that manual trades and generated signals never contaminate each other's performance metrics.
- [ ] Add tests for duplicate Telegram updates, repeated close events, partial exits, and interrupted journal writes.
- [ ] Require minimum sample sizes and display sample counts before historical learning influences a score.
- [ ] Add a database migration/backup/restore test plan before changing journal schema.
- [ ] Add a redacted diagnostics command that never prints tokens, keys, or private trade notes.

## Operating rules

- Work in small branches/PRs, attach regression tests, and keep changes reviewable.
- Do not merge when required CI is missing, failing, or still running.
- Prefer fixes that can be verified offline on Android/Linux over infrastructure that requires a server.
- A green test suite proves only the tested behavior; it does not prove trading profitability.
