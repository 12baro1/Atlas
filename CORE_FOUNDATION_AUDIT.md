# Core Foundation Audit

Audit target: `main` immediately after the Atlas main-decision-authority merge.

## Runtime reachability

| Module | Runtime status | Evidence / finding |
|---|---|---|
| `core/market_structure_engine.py` | Active | Imported by `engine.py`; `AtlasEngine._analyze_timeframe()` calls pivot detection, strength, noise filtering and sequence validation on timeframe analysis. |
| `core/pivot.py` | Active data model | Used by the active market-structure engine and legacy BOS detector. |
| `core/candle.py` | Active shared data model | Used by `data_engine.py`, backtest entry points, and multiple active engines/tests. |
| `core/analysis_utils.py` | Active shared helpers | Imported by risk, setup-quality, signal, volume-profile and institutional engines. |
| `core/swing_engine.py` | Legacy / test-only in searched runtime | Search found tests and label utilities, but no production engine import. Its ATR calculation nevertheless used the final dataset window for every historical bar, which could leak future volatility if reused in backtests. |
| `core/market_state.py` | Legacy plugin data model | Search found use in `plugins/bos/detector.py` and tests; not connected to the main engine's current market-analysis path. |
| `core/plugin.py` | Legacy plugin base | Imported by legacy BOS/CHOCH/FVG plugin adapters; no evidence that the main Atlas engine dispatches through this plugin API. |
| `core/plugin_manager.py` | Unreferenced by runtime | Repository search found no production instantiation/import. It is not the mechanism registering specialist motors with `AtlasMainEngine`. |

## Defects fixed in this audit branch

1. **Pivot filtering could suppress almost every pivot.** The active pipeline called `filter_noise()` with a default minimum strength of 14, while the default 5-left/5-right context contains at most 10 non-pivot candles. The default threshold is now 3, and strength uses only the configured left window plus the closed right confirmation window.
2. **Pivot window arguments were inconsistent.** The old detector normalized the stored right window but iterated using the unnormalized argument. Both windows are now validated and normalized once; zero/negative values raise a clear `ValueError`.
3. **Swing detector used future ATR.** A single ATR from the end of the entire candle series was used for every historical swing. It now calculates ATR as of each candle, using no later bars.
4. **OHLCV conversion trusted malformed rows.** `core.candle.convert()` now normalizes numeric strings, skips malformed/non-finite rows, rejects impossible OHLC geometry and negative volume.
5. **Shared analysis helpers accepted unsafe values.** Direction normalization strips whitespace; confidence extraction ignores non-finite values; `clamp()` handles invalid values safely and rejects invalid bounds.
6. **PluginManager ignored plugin validation.** It now checks `validate()`, prevents duplicate registration, reports unregister outcomes, supports returned replacement state as well as in-place mutation, and iterates over a stable plugin snapshot.

## Architectural gaps intentionally not hidden

- The legacy plugin framework is not the main specialist-motor orchestration path. Specialist engines in the active application are constructed and registered by `AtlasEngine` / `AtlasMainEngine`, not by `core.plugin_manager.PluginManager`.
- `MarketState` and the BOS/CHOCH plugin adapters are not currently part of the active unified decision pipeline. They should not be described as live decision motors until explicitly integrated and covered by end-to-end tests.
- `core.swing_engine` is not found in the production import path. Its causal fix prevents future leakage if it is reused, but it does not itself add a new live signal source.
- This audit covers the `core/` package and its direct runtime reachability. It does not certify profitability or replace full-market backtesting.

## Regression coverage added

- Active market-structure default pivot filtering and pivot-window validation.
- Strength bounded to the actual configured pivot context.
- Malformed OHLCV row rejection and numeric normalization.
- Finite-safe shared helper behavior.
- Plugin validation, duplicate registration, state replacement and unregister behavior.
- Swing detector causality under appended future candles.
