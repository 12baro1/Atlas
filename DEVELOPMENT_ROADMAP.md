# Atlas Engineering Roadmap

A living backlog, ordered by risk and user value. Do not mark an item complete without tests or a reproducible report.

## Release blockers / correctness

- [ ] Verify market-data timestamps and higher-timeframe candle boundaries, including exchange timezone and incomplete-candle edge cases.
- [ ] Audit live analysis paths for look-ahead bias, including cache restoration and all auxiliary SMC modules.
- [ ] Audit fee/slippage accounting across backtest and signal outcome tracking; prove each cost is applied exactly once.
- [ ] Test malformed, missing, stale, and incomplete market data; require WAIT rather than a fabricated setup.
- [ ] Confirm no execution path can place exchange orders, even if legacy environment variables or credentials are present.

## Signal quality and honest evaluation

- [ ] Add a reproducible out-of-sample backtest command with frozen parameters, transaction costs, expectancy in R, profit factor, maximum drawdown, sample count, and per-symbol breakdown.
- [ ] Add walk-forward evaluation and baseline comparison before changing signal thresholds.
- [ ] Calibrate heuristic score labels against observed outcomes; never label a score as probability without statistical calibration.
- [ ] Separate performance by symbol, direction, setup fingerprint, timeframe, and market regime when sample size permits.
- [ ] Audit dynamic RR/TP selection so targets are market-structure based, not artificially fixed.
- [ ] Verify signal expiry and prevent stale results from appearing actionable.
- [ ] Improve the `işlem ver` shortlist using reliable liquidity/volume data and a tested bounded scan budget.

## Terminal UX and reliability

- [ ] Test command parsing in Turkish and common ticker formats, including malformed and delisted symbols.
- [ ] Add deterministic tests for high-volume ranking, failed symbols, no-candidate behavior, and stable tie-breaking.
- [ ] Add a local status/diagnostics command for market-data provider, journal, and last successful analysis; never expose secrets.
- [ ] Test terminal interruption and restart recovery for local journal/state and atomic writes.
- [ ] Keep the UI to one screen and one input; do not reintroduce chat, AI, Telegram, or cloud dependencies.

## Journal and learning

- [ ] Verify manual trades and generated signal outcomes never contaminate each other's metrics.
- [ ] Test duplicate outcomes, repeated close events, partial exits, and interrupted journal writes.
- [ ] Require minimum sample sizes and display sample counts before historical learning affects a score.
- [ ] Add a database migration/backup/restore test plan before changing journal schema.

## Operating rules

- Work in small branches/PRs with regression tests.
- Do not merge when required CI is missing, failing, or still running.
- Prefer changes that can be verified offline on Android/Linux.
- A green test suite proves only tested behavior; it does not prove trading profitability.
