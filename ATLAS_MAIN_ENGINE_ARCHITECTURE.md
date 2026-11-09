# Atlas single-main-engine architecture

## Required flow

`Market data -> Specialist motors -> Shared evidence pool -> AtlasMainEngine -> One setup -> One decision`

## Runtime ownership

- `AtlasEngine.analyze()` enters through `AtlasMainEngine.analyze()`.
- The analysis adapter prepares the closed-candle/timeframe context and runs the registered specialist methods in dependency order.
- Each registered specialist is exposed through `MotorProxy`. A call is executed once, its raw result is recorded in the main engine's shared evidence pool, and exceptions are recorded and re-raised. Motor failures are not silently converted into neutral evidence.
- The specialist registry is explicit. Data/state services, journal, scanner and reporting components are not mislabeled as analysis motors.
- `market_structure` is registered dynamically for each timeframe analysis and its pivot/strength/merge/noise/sequence outputs are captured too.
- `AtlasMainEngine.build_setup()` is the only setup-construction entry point. It passes the complete specialist evidence trace and the structured specialist outputs to `SetupReasoningEngine`.
- The legacy `EntryEngine` and `EntryOptimizer` can contribute candidate/optimization evidence, but their result is not a second executable setup. If the main setup reasoner cannot select a valid POI, Atlas does not fall back to the legacy EntryEngine setup.
- `AtlasMainEngine.decide()` is the only final-decision entry point. The decision implementation is an internal subordinate component; its result is stamped with the main engine's authority.
- Macro news and duplicate-position cooldown remain operational hard gates. Correlation remains a warning/evidence input, not a directional veto.

## Motor audit output

After an analysis, `result["main_engine"]["motor_diagnostics"]` and
`result["analysis"]["motor_diagnostics"]["execution_trace"]` report:

- registered motors;
- motors invoked in this analysis;
- motors not invoked (for example, conditional feeds or disabled modules);
- call counts by motor;
- evidence count;
- errors.

A motor listed as not invoked is not automatically broken: some motors are conditional on configuration or supplied market data. An `ERROR` is a real execution failure and aborts the analysis rather than being hidden.

## Current limits

- Exchange/data ingestion remains upstream of the analysis engine. An input key such as order book, recent trades, open interest, funding, SMT universe or economic events is only available when the provider actually supplies it; unavailable feeds must not be described as live evidence.
- The shared evidence pool records the actual outputs, while the setup reasoner also receives typed state objects for its existing calculations. The evidence trace is not a replacement for validating each motor's domain logic.
- Static wiring and unit tests establish invocation contracts, not profitable trading performance. A same-data backtest and out-of-sample validation are still required before live use.
