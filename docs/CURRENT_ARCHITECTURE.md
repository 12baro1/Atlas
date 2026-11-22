# Atlas — Current Live Architecture (November 2026)

This document describes the **current** live processing contract, not the
historical seven-trade-strategy research design. Older audit reports and
`STRATEGY_PROFESSIONALIZATION.md` contain archived seven-generator proposals.

## Live flow

```text
Gate.io public market feeds / synchronized candle + L2/trade/OI/funding inputs
  -> data_engine + shared market/structure/microstructure analysis
  -> AtlasMainEngine specialist motor evidence (read-only)
  -> SevenStrategyLab (legacy class name, FIVE live generators)
      ├─ trend_pullback
      ├─ volatility_breakout
      ├─ mean_reversion
      ├─ orderflow_momentum
      └─ smc (its own submotors remain inside SMC)
      + relative_strength specialist (evidence only)
      + liquidation_cascade specialist (OI/funding proxy; evidence only)
  -> one common eligibility/risk/cost filter
  -> one final selected setup or SKIP
  -> validated opportunity pool
  -> explicit Telegram commands -> user-owned virtual trade tracking
  -> TP/SL/invalidation/change notifications and history
```

## Invariants

- Exactly five trade-generating strategy IDs, defined in
  `strategy_catalog.TRADE_STRATEGY_LABELS`.
- `relative_strength` and `liquidation_cascade` are analysis specialists,
  defined in `strategy_catalog.SPECIALIST_LABELS`. They cannot generate
  live setups, appear in live trade performance records, or be counted among
  trade strategy setup metrics.
- The legacy `strategies.relative_strength.strategy` and
  `strategies.liquidation.strategy` `generate()` entrypoints are disabled;
  their original algorithms remain available under
  `generate_research_candidate()` strictly for historical fixture tests.
- SMC's structural submotors are SMC-owned; shared specialists never
  independently decide trades.
- Telegram `/motorlar`, `/istatistik` and terminal TUI must distinguish
  **five trade strategies** from **two evidence specialists**.
- `/islemler` contains only user-requested follow-ups. Automatic pool
  publication may update an existing waiting trade but does not automatically
  enroll a new trade; terminal history stays separate.
- Atlas does not place exchange orders; tracking is virtual, not execution.
- Liquidation OI contraction and funding changes are **not** confirmed
  exchange liquidation events.

## Audit and operational limits

This contract is verified by code-level and CI regression tests. CI cannot
prove live exchange feed continuity, real fill quality, future profitability,
or VPS deployment state. Validate the deployed service separately after
merging a passing pull request. Do not clear the pool database to apply
this software migration.
