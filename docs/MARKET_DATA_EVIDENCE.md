# Atlas market-data evidence contract

Atlas receives several independent public market feeds. A connected socket is not
proof that every subscribed topic has delivered a usable snapshot. The authoritative
per-feed provenance is stored in `data_provenance`; derived status and age are
available in `shared_market_evidence`. The service also derives timestamped CVD,
executed-trade footprint, and displayed L2 liquidity-wall summaries once per snapshot.

## Raw feeds

| Feed | Live source | Primary consumers |
|---|---|---|
| Closed OHLCV (15m/1h/4h/1d/1w) | MEXC Futures REST | All seven strategies; timeframe requirements differ |
| Order book L2 | MEXC Futures WebSocket, REST fallback | Orderflow; optional shared context |
| Recent executed trades | MEXC Futures WebSocket, REST fallback | Orderflow and liquidation-cascade taker-flow proxy |
| Timestamped trade-flow batches | MEXC Futures public-deal WebSocket collector | Orderflow CVD |
| Liquidation events | Unavailable: MEXC has no documented public liquidation-event channel | Orderflow; liquidation-cascade event corroboration |
| Open interest | MEXC ticker OI snapshots observed over runtime (no historical OI endpoint) | Liquidation Cascade |
| Funding rate | MEXC ticker OI snapshots observed over runtime (no historical OI endpoint) | Liquidation Cascade |
| BTC/ETH comparison candles | MEXC Futures REST | Relative Strength, SMT/correlation consumers |
| Configured sector peers | MEXC Futures REST | Relative Strength |

## Per-strategy input contract

- Trend Pullback: 4H and 1H closed candles, current price.
- Volatility Breakout: 1H closed candles, current price.
- Mean Reversion: 15m closed candles and range-regime classification.
- Liquidation Cascade: 1H candles, at least two timestamped OI observations, recent taker trades, funding context. Actual liquidation events are reported separately as corroborating evidence; OI contraction is explicitly a proxy.
- Orderflow Momentum: fresh L2 order book, fresh recent trades, 15m candles, footprint from executed trades and timestamped CVD batches. MEXC public liquidation events are unavailable.
- Relative Strength: 4H candles, aligned BTC/ETH benchmark returns, and configured sector peers when available.
- SMC: closed multi-timeframe candles plus the SMC specialist analysis result and its internal submotors. It does not require the order book to manufacture an SMC setup.

Strategies do not inherit one another's setup decisions. The shared evidence object is
read-only context; each strategy retains its own entry logic. The shared eligibility
filter and the single decision selector remain downstream.

## Data-quality rules

- Each feed has its own source, timestamp, age and availability state.
- A socket being connected does not make an empty book/trade/liquidation feed
  available.
- Order book freshness is 15 seconds; recent trade freshness is 30 seconds;
  CVD freshness is 5 minutes; liquidation event freshness is 15 minutes; OI
  freshness is 2 hours; funding freshness is 8 hours.
- A single OI snapshot is not OI history and cannot establish contraction. MEXC OI contraction becomes available only after Atlas has observed at least two timestamped holdVol snapshots during runtime; historical OI replay remains unavailable.
- Missing timestamps are not replaced with fabricated historical observations.
- Bybit `allLiquidation` field `S` is position side: `Buy` means a long position
  was liquidated; `Sell` means a short position was liquidated.
- Absorption is a public-trade/candle proxy, not directly observed passive absorption.
- Displayed order-book walls may be cancelled and are not guaranteed support/resistance.
- Historical order-book/trade replay requires locally archived timestamped snapshots;
  no synthetic historical microstructure is generated.

## Diagnostics

Each strategy result now includes `data_usage`:
- `generator_inputs`: whether each native input meets its minimum history,
  freshness or sample-size requirement.
- `analysis_features`: the concrete indicator/evidence families used by that
  strategy's own generator.
- `shared_source_status`: source-level status and provenance from the shared evidence
  snapshot, including CVD freshness.

This is availability/provenance telemetry, not an extra shared strategy filter. A
strategy may still reject a setup because its native pattern conditions do not align.
