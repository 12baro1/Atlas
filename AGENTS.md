# Atlas Agent Contract

These rules apply to every coding agent working in this repository.

## Product constraints

- Atlas is a local-first SMC analysis and manual-signal assistant, not an exchange execution bot.
- Never add, enable, or restore live exchange order placement. Keep the order-execution safety lock hard-coded and test it.
- Public market data may be fetched for analysis. Never require exchange trading credentials for market-data-only workflows.
- The user's target runtime is Android + UserLAnd/Ubuntu on a phone; do not require a VPS, hosted database, or always-on cloud service.
- AI inference must be local and API-free by default. Do not silently send prompts, account data, trade journals, or market context to a remote provider. Do not silently fall back to a remote API when the local model is offline.
- Never fabricate prices, candles, fills, trade outcomes, model status, backtest results, or confidence. Distinguish heuristic setup scores from win probabilities.
- Keep the Telegram signal compact: symbol, LONG/SHORT/WAIT, entry, stop loss, TP1/TP2/TP3, expected gain, risk/reward, grade, and heuristic score. Keep internal diagnostics out of the user-facing signal unless explicitly requested.
- Manual trade records and automatically generated signal outcomes must remain distinct data sources.

## Required engineering loop

1. Inspect the real implementation, call sites, configuration, and tests before editing.
2. Identify a concrete defect or measurable improvement. Prefer small changes with regression tests over speculative rewrites.
3. Never make an unrelated refactor while fixing a bug.
4. Add deterministic offline tests. Tests must not need live exchange data, Telegram credentials, remote LLMs, or network access.
5. Run the narrow test first, then compile checks and the full test suite when the environment permits.
6. Review the diff for data leakage, look-ahead bias, false confidence, unsafe execution paths, and accidental credential exposure.
7. Report exactly what was changed and which checks actually ran. Never claim tests passed when they were not run.
8. Use a dedicated branch and pull request for substantive changes. Do not force-push, delete user data, or merge a change whose required checks have not passed.
9. If a test cannot be run in the available environment, state the limitation and leave the change unmerged until CI validates it.
10. Continue with the next highest-value issue without asking the user to re-approve routine, reversible engineering decisions.

## Trading-system quality bar

- Treat look-ahead prevention and timestamp alignment as release blockers.
- Calculate fees and slippage consistently; do not double-count costs.
- Use out-of-sample backtests, realistic transaction costs, and drawdown/expectancy metrics. Do not tune only to win rate.
- Require enough observations before historical performance affects scores. Show sample size and scope; avoid mixing unrelated symbols/setups.
- Keep unknown or non-finite values unknown or safely neutral; never convert missing evidence into a strong signal.
- Do not present a heuristic score as a probability or guarantee of profit.
- Default to WAIT when required market data is missing, stale, incomplete, or invalid.

## Local AI agent quality bar

- Prefer structured tool calls to keyword-based hardcoded responses.
- Validate every tool name and argument against an allowlist/schema before dispatch.
- Keep a bounded conversation history and handle malformed model output, timeouts, and unavailable local inference cleanly.
- The agent must be able to report that local AI is offline; it must not pretend an LLM call succeeded.
- Preserve useful state locally across terminal restarts, with atomic writes and safe handling of interrupted writes.

## Definition of done

A change is done only when its behavior is covered by tests, the diff has been reviewed, the relevant checks have actually passed, and the user-facing report clearly distinguishes verified results from pending validation.
