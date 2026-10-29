# Atlas Agent Contract

These rules apply to every coding agent working in this repository.

## Product constraints

- Atlas is a terminal-only SMC analysis tool for Android + UserLAnd/Ubuntu.
- The product UI has one screen and one command input. `atlas` opens it; entering a coin symbol analyzes that market; `işlem ver` searches for the best currently valid setup in a bounded high-volume shortlist.
- Do not add a chat assistant, LLM provider, model download/startup, Telegram bot, Telegram notifications, VPS requirement, or cloud service to the product workflow.
- Never add, enable, or restore live exchange order placement. Keep the order-execution safety lock hard-coded and test it.
- Public market data may be fetched for analysis. Never require exchange trading credentials for market-data-only workflows.
- Never fabricate prices, candles, fills, trade outcomes, backtest results, or confidence. Distinguish heuristic setup scores from win probabilities.
- If no setup passes the real decision/risk checks, display WAIT/ATLA instead of forcing a trade.
- Keep the result readable: symbol, LONG/SHORT/WAIT, entry, stop loss, TP1/TP2/TP3, RR, grade/heuristic score, and concise blockers where useful.
- Keep manual trade records and automatically generated signal outcomes distinct.

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
- Use out-of-sample backtests, realistic transaction costs, expectancy in R, profit factor, sample size, and drawdown. Do not tune only to win rate.
- Require enough observations before historical performance affects scores. Show sample size and scope; avoid mixing unrelated symbols/setups.
- Ensure target selection follows market structure and is not artificially fixed to a preferred RR.
- Verify signal expiry and prevent stale results from appearing actionable after the market has moved.
- Keep unknown or non-finite values unknown or safely neutral; never convert missing evidence into a strong signal.
- Default to WAIT when required market data is missing, stale, incomplete, or invalid.
- A ranked setup score is not a win probability and is not evidence of profitability.

## Terminal and reliability quality bar

- Keep one screen and one command field; avoid multipage dashboards, chat UI, and notification services.
- `işlem ver` must use a bounded, documented scan and must explain when no valid setup exists.
- Handle malformed symbols, unavailable market data, timeouts, and invalid numeric values cleanly.
- Preserve useful local journal/state across restarts with atomic writes and safe recovery.
- Do not print secrets or private journal notes in diagnostics.

## Definition of done

A change is done only when its behavior is covered by tests, the diff has been reviewed, the relevant checks have actually passed, and the user-facing report clearly distinguishes verified results from pending validation.
