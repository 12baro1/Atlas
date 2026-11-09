# Atlas Architecture Maintenance Audit

Audit baseline: current `main` after the core-foundation fixes. The terminal entrypoint is `atlas_app.py` -> `atlas_runtime.py` -> `AtlasEngine` -> `AtlasMainEngine`. The CLI is local-only: it disables Telegram and AI and does not send exchange orders.

## Active modules with stale maintenance history

The dates below are the last commit dates observed on the audit baseline, not proof that a file is defective. These modules were checked against the live call graph and updated only where a concrete correctness or resilience defect was found.

| Module | Last change on audit baseline | Runtime role | Audit result |
|---|---:|---|---|
| `cisd_engine.py` | 2026-07-18 | Active MTF evidence consumed by the main decision | Fixed neutral delivery being misclassified as bearish CISD |
| `premium_discount_engine.py` | 2026-07-17 | Active context input to market phase and entry quality | Added finite/positive input validation and explicit equilibrium state |
| `session_filter.py` | 2026-08-07 | Active session context motor | Fixed overlap calculation to require both configured windows to be active |
| `statistics_engine.py` | 2026-08-07 | Active signal statistics recorder | Rejects malformed/non-finite values; zero RR is retained as a valid value |
| `timing.py` | 2026-08-08 | Shared live/backtest HTF close boundary | Fixed unsorted candle input truncating valid earlier candles; output is chronological |
| `economic_news_engine.py` | 2026-07-26 | Active hard safety gate | Skips malformed events, normalizes seconds/ms timestamps, preserves timestamp zero |
| `trade_cooldown_engine.py` | 2026-07-26 | Active duplicate-position/cooldown gate | Preserves explicit zero timestamps, validates finite values and malformed positions |
| `state_engine.py` | 2026-08-07 | Active persistent cache and open-position restore | Sanitizes persisted schema and guards corrupt cache fields |
| `learning_engine.py` | 2026-08-10 | Active journal-fed setup-quality adjustment | Sanitizes legacy state migration and writes atomically |
| `scanner_engine.py` | 2026-10-29 | Active aggregation of final analysis payloads | Requires explicit risk validation and finite, directionally ordered entry/SL/TP geometry before marking a row tradable |

## Active modules reviewed; no speculative rewrite

- `unicorn_engine.py` (last change 2026-07-18): active MTF breaker/FVG evidence. Directional validation was corrected; its proposed levels remain evidence only and the main engine performs final setup geometry reconciliation.
- `universe_engine.py` (last change 2026-07-18): active symbol filtering used by the terminal scanner and data selection. The USDT perpetual symbol suffix and exchange market metadata provide the current contract filter.
- `killzone_engine.py` (last change 2026-08-07): active UTC kill-zone context, shares the current Config session windows.
- `canonical_features.py` (last change 2026-08-08): active canonical feature vocabulary shared by journal learning and setup quality.
- `trade_manager.py` (last change 2026-07-20): instantiated only as a backward-compatibility attribute; no production `build()` call exists in the current engine path. It is not an authority and must not be reintroduced as a second decision maker.

## Legacy / dormant code kept out of the live decision path

- `scanner.py` (last change 2026-08-02) was an older standalone raw CCXT scanner that loaded markets at import time and bypassed the main runtime. It is now a side-effect-free compatibility wrapper around `atlas_app.main`, matching `main.py` and `atlas_entry.py`.
- `main.py` and `atlas_entry.py` are thin backward-compatible wrappers around `atlas_app.main`.
- `execution_engine.py` is an intentional compatibility alias for `BybitExecutionEngine`; the terminal analysis workflow does not send orders.
- `core/market_state.py` and `plugins/bos|choch|fvg|liquidity` are legacy plugin-era components. The current main engine uses root specialist engines and `core.market_structure_engine`; no current main-engine dispatch through `core.plugin_manager` was found.
- `core.swing_engine.py` is not imported by the production analysis path found in this audit; it remains legacy/test support.
- `ai/` modules are not started by the terminal entrypoint. `AtlasRuntime.initialize_ai()` and `ai_status()` are disabled compatibility stubs.
- `telegram_*` modules and Telegram branches remain in the legacy engine/runtime for compatibility, but the supported terminal entrypoint forcibly disables Telegram. They are not part of the intended terminal workflow.

These dormant files were not blindly deleted or wired back into the main engine. Deletion would be a compatibility/API change and is separate from correctness fixes to the active pipeline.

## Regression coverage added

- Neutral CISD transition cannot emit a false directional event.
- Premium/discount input validation and equilibrium behavior.
- Session overlap requires simultaneous configured session membership.
- Statistics remain finite when metrics are malformed and preserve journal output semantics.
- HTF candle filtering is safe for unsorted input and invalid reference timestamps.
- Economic news skips malformed rows and preserves explicit zero timestamps.
- Cooldown preserves zero timestamps, rejects future signal timestamps and tolerates malformed positions.
- State persistence ignores malformed top-level sections and cache shapes.
- Learning persistence sanitizes malformed legacy buckets and uses atomic replacement.
- Scanner rejects missing, non-finite, directionally invalid or unvalidated trade geometry.
- Legacy `scanner.py` import no longer starts a CCXT market request or a separate scanning implementation.

## Validation boundary

A passing unit suite proves the covered code paths and regressions, not profitability. After merge, compare the same symbols, timeframes, period, fees and slippage against the previous baseline. Do not infer a win-rate improvement from code changes alone.
