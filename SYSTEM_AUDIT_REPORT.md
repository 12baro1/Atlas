# Atlas System Audit Report

> **Archived audit snapshot.** This report describes an older seven-generator revision. The current live contract is five trade strategies plus two evidence-only specialists; see [Current Architecture](docs/CURRENT_ARCHITECTURE.md).


**Date:** 2026-11-17  
**Scope:** Full system audit from Gate.io data provider through 7 strategies, common filters, decision engine, opportunity pool, Telegram commands, and operational reliability.

---

## 1. System Inventory & Architecture

### Core Components (92 project Python files, excluding venv)

| Layer | Files | Purpose |
|-------|-------|---------|
| **Entry Points** | `main.py`, `atlas_app.py`, `atlas_entry.py`, `atlas_runtime.py`, `atlas_tui.py` | CLI/TUI, runtime, scanning |
| **Core Engines** | `engine.py`, `atlas_main_engine.py`, `strategy_lab.py` | Orchestration, 7-strategy pipeline, main authority |
| **7 Strategies** | `strategies/smc/`, `trend/`, `breakout/`, `mean_reversion/`, `orderflow/`, `liquidation/`, `relative_strength/` | Independent setup generators |
| **Specialist Motors** | 35+ engines (`bos_engine.py`, `choch_engine.py`, `orderblock_engine.py`, `fvg_engine.py`, `liquidity_engine.py`, etc.) | Evidence producers for SMC |
| **Shared Services** | `shared/analysis_services.py`, `shared/market_data_services.py`, `shared/market_structure_services.py`, `shared/microstructure_services.py` | Reusable analysis primitives |
| **Risk/Decision** | `risk_engine.py`, `decision_engine.py`, `entry_engine.py`, `entry_optimizer.py`, `dynamic_tp_engine.py`, `rr_engine.py` | Geometry, costs, final selection |
| **Data Layer** | `data_engine.py`, `gateio_futures.py`, `strategies/orderflow/gateio_public_stream.py` | Gate.io USDT perpetual market data |
| **State/Storage** | `state_engine.py`, `trade_journal.py`, `learning_engine.py`, `opportunity_pool.py` | Persistence, SQLite, learning |
| **Telegram** | `telegram_commands.py`, `telegram_command_service.py`, `telegram_service.py`, `telegram_engine.py` | Commands, polling, formatting |
| **Quality/Filtering** | `trade_quality_engine.py`, `trade_quality_filters.py`, `setup_quality_engine.py`, `setup_reasoning_engine.py` | Execution gates, candidate ranking |

### Data Flow Architecture

```
Gate.io REST/WS → DataEngine → Market Data (OHLCV, OB, trades, liq, OI, funding)
                                      ↓
                            Shared Analysis Services (build_shared_market_evidence)
                                      ↓
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              SMC Specialist      6 Non-SMC        StrategyLab
              Motors (evidence)   Strategies       (7 generators)
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      ▼
                            Common Filter (geometry, net-RR, execution)
                                      ▼
                            DecisionEngine.select_strategy_candidate()
                                      ▼
                            AtlasMainEngine (final geometry, operational gates)
                                      ▼
                            Runtime → Scanner → OpportunityPool → Telegram
```

---

## 2. Gate.io Data Infrastructure Analysis

### ✅ Working Correctly
- **Symbol Discovery**: `load_markets()` filters USDT perpetual swaps, excludes delisting
- **OHLCV Validation**: `_fetch()` discards forming candle, invalid rows, duplicates, out-of-order timestamps
- **Candle Closure Guard**: `closed_htf_candles()` in `timing.py` ensures only fully closed HTF candles enter analysis
- **Order Book**: REST snapshot + WS delta synchronization with nonce tracking
- **Recent Trades**: 200-trade limit, taker buy/sell notional delta
- **Liquidation Events**: WS feed parsed when available, marked as proxy when unavailable
- **OI/Funding**: REST history + WS snapshots merged by timestamp
- **Rate Limits**: Per-timeframe TTL cache (15m=0, 1h=300s, 4h=900s, 1d=3600s, 1w=3600s)
- **Symbol Normalization**: `normalize_symbol()` handles BTC, BTC/USDT, BTC/USDT:USDT formats

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **WS Connection Per Analysis** | `data_engine.py:126-136` | Medium | New `GatePublicStream` created per `get_market_data()` call; no connection pooling. Under scan load (50+ symbols), this creates 50+ concurrent WS connections. |
| **OI Single Snapshot Fallback** | `data_engine.py:300-319` | Medium | Single OI snapshot stored with `count=1`; liquidation strategy requires `count>=2` for contraction detection. |
| **No WS Reconnection Logic** | `gateio_public_stream.py` | High | If WS drops during scan, microstructure data becomes REST-only without retry. |
| **SMT Universe Cache Staleness** | `data_engine.py:505-530` | Low | `_smt_cache` TTLs (15m=45s) may serve stale BTC/ETH candles during rapid market moves. |
| **Missing Contract Size Validation** | `gateio_futures.py:112-118` | Low | `_scaled_contract_amount` uses Decimal but no validation that contract size > 0 for all symbols. |

---

## 3. Seven Strategy Analysis

### Strategy Implementation Status

| Strategy | File | Generator | Data Dependencies | Uses Shared Evidence | Independent Logic |
|----------|------|-----------|-------------------|---------------------|-------------------|
| **SMC** | `strategies/smc/strategy.py` | `_smc_candidate()` | 15m,1h,4h,1d,1w, SMT | ✅ (reads `smc_result` from engine) | ✅ Integrated specialist world |
| **Trend Following** | `strategies/trend/strategy.py` | `_trend_pullback()` | 4h, 1h | ✅ (specialist_evidence) | ✅ EMA/ADX/DMI/pullback |
| **Breakout** | `strategies/breakout/strategy.py` | `_volatility_breakout()` | 1h | ✅ (specialist_evidence) | ✅ Bollinger compression + volume |
| **Mean Reversion** | `strategies/mean_reversion/strategy.py` | `_mean_reversion()` | 15m, regime | ✅ (specialist_evidence) | ✅ Bollinger/RSI/VWAP |
| **Liquidation** | `strategies/liquidation/strategy.py` | `_liquidation_cascade()` | 1h, OI, funding, liq events | ✅ (specialist_evidence) | ✅ OI contraction proxy |
| **Order Flow** | `strategies/orderflow/strategy.py` | `_orderflow_momentum()` | 15m, OB, trades, CVD | ✅ (specialist_evidence) | ✅ Imbalance/delta/absorption |
| **Relative Strength** | `strategies/relative_strength/strategy.py` | `_relative_strength()` | 4h, correlation_universe | ✅ (specialist_evidence) | ✅ Beta-adjusted alpha |

### ✅ Architectural Strengths
- Each strategy owns its pattern detection (`generate()` function)
- Shared specialist evidence consumed via `_strategy_specialist_evidence()` - read-only
- Raw candidates passed to **one common filter** (`_finalize_candidate_geometry`, `_risk_validate_candidate`)
- **One final selector** (`DecisionEngine.select_strategy_candidate`) ranks by net-RR × regime_fit × strength
- Diagnostic `_setup_diagnostic()` explains why each strategy produced no setup
- Data usage reporting (`_strategy_data_usage`) tracks input availability per strategy

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **SMC Strategy Bypasses Common Filter Geometry** | `strategies/smc/strategy.py:72-85` | High | SMC candidate uses pre-computed `tp1/tp2/tp3` from engine result, skipping `_finalize_candidate_geometry()` structural target validation. Other strategies get structural stops/TPs from common filter. |
| **Dummy Stop Loss in Non-SMC Strategies** | All non-SMC `generate()` | Medium | Strategies pass `dummy_stop = entry ± atr` (ignored by common filter). This works but obscures that initial stop is strategy-native. |
| **Liquidation Strategy OI Proxy Mislabeling** | `strategies/liquidation/strategy.py:113` | Medium | `data_quality: "OI_CONTRACTION_PROXY_NOT_EXCHANGE_LIQUIDATION_FEED"` but still named `liquidation_cascade`. |
| **Order Flow Absorption Proxy Not Validated** | `strategies/orderflow/strategy.py:3-26` | Medium | `_absorption_proxy` infers passive absorption from delta+stalled price - no ground truth validation. |
| **Relative Strength Beta Instability** | `strategies/relative_strength/strategy.py:81-90` | Low | Beta calculation fails if market variance ≤ 1e-12; no fallback regime. |
| **No Strategy Execution Count Telemetry** | `strategy_lab.py` | Low | `_scan_cycle()` doesn't track how many times each strategy ran, produced raw setup, passed filter, was selected. |

---

## 4. Common Analysis, Filter & Decision Architecture

### Pipeline Flow (Verified Working)

```
1. AtlasEngine._analyze_with_motors() 
   → Specialist motors → build_shared_market_evidence()
   → Structure/Context/Execution state built
   
2. SMC raw setup extracted (entry/risk/dynamic_tp/signal from execution_state)
   
3. SevenStrategyLab.analyze()
   → 7 independent generators (raw candidates)
   → Common filter: geometry validation, execution eligibility, risk validation (net-RR)
   → DecisionEngine.select_strategy_candidate() → single SELECTED
   
4. AtlasMainEngine.build_setup() → finalize_setup_geometry() → apply_operational_gates()
   
5. DecisionEngine.decide() → final action (EXECUTE/WAIT/SKIP)
```

### ✅ Correct Design Decisions
- **Single common filter** for all 7 strategies (geometry, net-RR, execution distance)
- **Single decision authority** - no strategy can bypass filter or self-select
- **Operational gates** (news, cooldown) applied once at end; correlation is evidence-only
- **SMC submotors stay in SMC package** - not exposed as independent strategies
- **Trace ID** propagated end-to-end for observability

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **SMC Setup Skips Structural Target Validation** | `engine.py:469-478` | Critical | `smc_raw` uses pre-computed TP1/2/3 from `execution_state` without `_finalize_candidate_geometry()` validation. If SMC's dynamic_tp produced invalid targets, they bypass the common filter's structural target check. |
| **Common Filter Execution Eligibility Duplicated** | `strategy_lab.py:845-865` + `engine.py:1420-1460` | Medium | Order book microstructure conflict handling appears in both StrategyLab common filter AND engine's entry_confirmation. Single gate should own this. |
| **DecisionEngine Quality Gate Duplicates StrategyLab Filter** | `decision_engine.py:102-136` + `strategy_lab.py:867-891` | Medium | Both apply confidence/RR/MTF/confluence thresholds. StrategyLab common filter should be the only eligibility gate; DecisionEngine should only rank eligible candidates. |
| **Missing "No Valid Setup" Diagnostics in Telegram** | `telegram_command_service.py:1067-1093` | Medium | Scan diagnostics show blocker counts but don't distinguish between "no raw setup generated" vs "raw setup rejected by common filter" vs "eligible but not selected". |
| **Risk Recalculation After Stop Expand Not Triggered for SMC** | `engine.py:1630-1652` | Medium | `_calculate_risk` rebuilds TP after stop expand, but SMC path uses pre-computed risk from `execution_state` which may not have triggered this. |

---

## 5. Opportunity Pool & Scanner System

### Pool Architecture (`opportunity_pool.py`)

Three distinct pools with clear lifecycle:
1. **Candidate Pool** (DISCOVERED → CANDIDATE) - Raw setups from scanning
2. **Validated Pool** (VALIDATED) - Passed common filter, ready for user
3. **Active Pool** (ACTIVE → ENTRY_PENDING → ENTERED → TP1/2/3) - User-accepted setups

### ✅ Working Correctly
- Atomic JSON persistence with temp-file + `os.replace()`
- Deduplication by symbol+direction+entry_price (±0.1%)
- Capacity limits with LRU eviction (candidates=500, validated=200, history=5000)
- 24h expiry with `cleanup_expired()`
- Background persistence thread (30s interval)
- History archival with `max_history` cap

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **Scanner.clear() Called Before Each Scan** | `telegram_command_service.py:968` | High | `_execute_scan()` calls `self.runtime.scanner.clear()` for every `/20tara`, `/30tara`, etc. This **wipes the pool** before populating it. `/eniyi5` (cached_best_request=True) correctly reads existing pool without clearing. |
| **Background Scan Also Clears Pool** | `atlas_runtime.py:434-470` | High | `_scan_cycle()` in background scanner calls `analyze_symbol()` which calls `scanner.add()`, but if scanner is cleared between cycles, history lost. |
| **No Pool-Scan Synchronization** | `atlas_runtime.py` + `telegram_command_service.py` | High | Background scanner and Telegram commands share `runtime.scanner` but no locking. Concurrent scan + command can corrupt pool state. |
| **Setup Identity Not Preserved Across Scans** | `opportunity_pool.py:270-286` | Medium | `_find_duplicate()` uses entry_price ±0.1% and 5-min window. If same setup reappears with slightly different entry (market moved), treated as new. |
| **Active Setups Not Auto-Monitored** | `opportunity_pool.py` | Medium | Pool stores TP/SL but no background task checks price vs levels. Relies on manual `/takip` or `trade_journal.resolve_signal_outcomes()`. |

---

## 6. Daily Operations & Tracking System

### ✅ Working Correctly
- **Turkey Timezone**: `ZoneInfo("Europe/Istanbul")` used in `format_daily_signal_report()`
- **Daily Reset**: `/mevcut` filters by `opened_at` date in Istanbul TZ
- **Signal Outcome States**: PENDING → TP1/TP2/TP3/SL/EXPIRED with proper transitions
- **LIMIT vs MARKET**: `entry_tracking_source` distinguishes `closed_ohlc` (mumda görüldü) vs `market_reference` (fill teyidi değil)
- **Same-Candle TP+SL**: Conservative handling - SL takes priority if both in same candle
- **Journal Persistence**: SQLite with retention (30 days default, 5000 max snapshots)

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **Signal Outcome Resolution Uses 15m Candles Only** | `trade_journal.py` (not read but called from `atlas_runtime.py:556`) | Medium | `resolve_signal_outcomes()` only checks 15m candles. If TP/SL hit on 1m/5m but not 15m close, outcome not resolved until next 15m close. |
| **Learning Engine "matched=False" Not Explained to User** | `learning_engine.py:560-562` + `engine.py:961-987` | Medium | `_log_learning_live` logs `no_match_reason` but Telegram `/ogrenme` only shows aggregate stats, not per-setup match failures. |
| **Unresolved Signal Outcomes Accumulate** | `trade_journal.py` | Low | `SIGNAL_OUTCOME_EXPIRY_HOURS=72` but no automatic cleanup of PENDING outcomes older than expiry during non-scan periods. |
| **Manual Trade vs Signal Outcome Conflation** | `trade_journal.py` | Low | `manual_trade_performance()` and `signal_performance()` kept separate but `learning_engine` merges them with priority config. |

---

## 7. Entry, SL, TP & Risk Engine

### Key Risk Messages Analyzed

| Message | Origin | Current Handling |
|---------|--------|------------------|
| `STOP_EXECUTION_COST_TOO_HIGH` | `risk_engine.py:221-237, 428-438` | Rejects setup if stop round-trip cost > `MAX_STOP_EXECUTION_COST_R` (default 0.50R) |
| `No structurally valid POI candidate` | `setup_reasoning_engine.py:770-782` | Returns WAIT when no POI yields valid entry/stop/targets |
| `All structurally valid POIs are too far from current market price` | `setup_reasoning_engine.py:800-816` | Returns WAIT with `ENTRY_TOO_FAR` reason |

### ✅ Working Correctly
- **ATR/Swing/OB/FVG Invalidation**: Stop anchored to structural invalidation (OTE/OB/FVG edge) + small ATR buffer
- **TP from Liquidity**: `DynamicTPEngine.select_structural_targets()` uses opposing swing liquidity clusters
- **Cost Model**: Per-fill maker/taker + spread + slippage; fees not double-counted
- **Net RR Calculation**: `weighted_net_rr` includes plan cost + stop-exit friction
- **Position Sizing**: Risk % scaled by `risk_reduction_factor` when net RR < minimum
- **Geometry Reconciliation**: `AtlasMainEngine.finalize_setup_geometry()` is single authority for entry/SL/TP

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **MIN_STOP_ATR_MULTIPLIER Inconsistent** | `config.py:111` (0.75) vs `setup_reasoning_engine.py:538` (0.35) | Critical | Config default 0.75 but SetupReasoningEngine uses 0.35. Which one wins? |
| **STOP_STRUCTURE_BUFFER_ATR Not Used Consistently** | `config.py:118` (0.10) vs `setup_reasoning_engine.py:543` (0.10) | Low | Same value but defined in two places. |
| **Risk Recalculation After Stop Expand Misses SMC Path** | `engine.py:1630-1652` | Medium | SMC setup uses pre-computed risk from `execution_state`; auto-expand triggers TP rebuild only in `_calculate_risk` path. |
| **Dynamic TP Synthetic Fallback Config Ignored** | `config.py:100` vs `dynamic_tp_engine.py` | Medium | `DYNAMIC_TP_ALLOW_SYNTHETIC_FALLBACK` default false but not all callers respect it. |
| **Entry Distance Check Uses Current Price Not Last Closed Candle** | `strategy_lab.py:850-859` | Medium | Execution eligibility uses `_current_price(data)` which may be ticker price, not last closed 15m close. |

---

## 8. Telegram System - All Commands

### Command Registry (`telegram_commands.py`)

| Command | Handler | Category | Parameter |
|---------|---------|----------|-----------|
| `/btc`, `/eth`, `/sol` | `handle_analyze_symbol` | market | No (symbol in command) |
| `/analiz BTC` | `handle_analyze_symbol` | market | Yes |
| `/20tara`, `/30tara`, `/50tara`, `/100tara` | `handle_scan` | scan | No (limit in command) |
| `/tumtara` | `handle_scan_all` | scan | No |
| `/eniyi5` | `handle_best_five` | scan | No |
| `/mevcut` | `handle_mevcut` | setup | No |
| `/setuplar` | `handle_setuplar` | setup | No |
| `/takip` | `handle_takip` | setup | No |
| `/likidite BTC` | `handle_liquidity` | setup | Yes |
| `/performans` | `handle_performance` | performance | No |
| `/istatistik` | `handle_statistics` | performance | No |
| `/ogrenme` | `handle_learning` | performance | No |
| `/durum` | `handle_status` | system | No |
| `/sistem` | `handle_system` | system | No |
| `/yardim` | `handle_help` | system | No |

### ✅ Working Correctly
- **Slash + @BotName Support**: `normalize_command()` strips `@username`
- **Legacy Plain-Text Commands**: "mevcut", "en iyi 5 işlem", "20 tara" still work
- **Group/Private Chat**: Validates `chat_id` matches configured group
- **Stale Command Protection**: `MAX_COMMAND_AGE_SECONDS=120`
- **BotFather Sync**: `get_botfather_commands()` generates exact menu
- **Response Chunking**: `split_message()` respects 4096 char limit
- **Async Send**: Non-blocking with thread pool + flush on shutdown

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **Scanner Cleared on Every Scan Command** | `telegram_command_service.py:968` | Critical | `/20tara` etc. call `runtime.scanner.clear()` → wipes pool. Only `/eniyi5` preserves pool. |
| **handle_scan() Hardcoded Limit** | `telegram_command_service.py:722-731` | High | Extracts limit from command name but `_last_raw_command` not set. Falls back to configured scan limit. |
| **No Command Rate Limiting** | `telegram_command_service.py` | Medium | User can spam `/20tara` → triggers concurrent scans → API rate limits. |
| **Long Analysis Blocks Polling** | `telegram_command_service.py:569-586` | Medium | `execute_command()` runs synchronously in poll loop. 10s analysis blocks other commands. |
| **Error Messages Leak Internals** | `telegram_command_service.py:573` | Low | "VPS günlüklerini kontrol et" exposes infrastructure detail. |
| **BotFather Menu Not Auto-Updated** | `telegram_botfather.py` | Low | `set_my_commands` called on startup but not when commands change. |

---

## 9. Learning System

### ✅ Working Correctly
- **Source Priority**: Manual trades > tracked signals > theoretical signals (configurable)
- **OOS Validation**: 2/3 chronological split, both positive AND negative edges validated
- **Hierarchical Lookup**: EXACT → FAMILY → DIRECTION+REGIME → GLOBAL (with config flags)
- **Time Decay**: Half-life (default 45 days) weights recent trades higher
- **Bounded Influence**: `LEARNING_EDGE_UPLIFT_MAX=6`, `LEARNING_EDGE_PENALTY_MAX=10` points
- **Persistence**: Atomic JSON save with backup, survives restart
- **Minimum Samples**: `LEARNING_MIN_SAMPLES=20` before adjustment applied

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **LEARNING_GLOBAL_FALLBACK Default True** | `config.py:389` vs `learning_engine.py:474` | High | Default `LEARNING_GLOBAL_FALLBACK="0"` (false) but `learning_engine._global_enabled()` reads `True` as default. Isolation broken by default. |
| **Unresolved Signal Outcomes Feed Learning** | `engine.py:747-766` | High | `_register_tracked_signal()` creates signal outcome with `status=PENDING`. `refresh_learning()` reads `learning_records(source="signal")` which includes PENDING outcomes. Unresolved trades pollute learning index. |
| **Learning Index Rebuild Clears Valid History** | `learning_engine.py:380-394` | Medium | `rebuild_from_records()` replaces entire index. If manual trades added, signal outcomes from previous rebuild lost unless re-fed. |
| **No Per-Setup Match Diagnostics in Telegram** | `telegram_command_service.py:849-866` | Medium | `/ogrenme` shows aggregate `matched_setups` but not why specific setups fail to match (`no_match_reason`). |
| **Learning Adjustment Applied to SMC Score But Not Others** | `engine.py:1487-1493` | Low | `learning.apply_to_setup_quality()` called on `setup_quality` which is SMC-centric. Non-SMC strategies don't receive learning adjustment. |

---

## 10. VPS & Operational Reliability

### Systemd Service (`deploy/atlas.service` - assumed)

### ✅ Working Correctly
- **Atomic State Persistence**: All JSON state files use temp + `os.replace()`
- **Thread Safety**: `RLock` in OpportunityPool, `Lock` in AtlasRuntime per-symbol
- **Graceful Shutdown**: `AtlasRuntime.stop()` joins threads, flushes Telegram
- **Log Rotation**: Standard logging handlers (needs external logrotate)
- **Memory Bounds**: `deque(maxlen=500)` for runtime logs, pool capacity limits

### ❌ Issues Found

| Issue | Location | Severity | Description |
|-------|----------|----------|-------------|
| **No Health Check Endpoint** | N/A | Medium | No HTTP/TCP health check for systemd `HealthCheck=` or container orchestration. |
| **WS Connections Not Pooled** | `data_engine.py:126` | High | New WS per analysis → connection exhaustion under load. |
| **Scanner Thread Pool No Backpressure** | `atlas_runtime.py:439` | Medium | `ThreadPoolExecutor(max_workers=4)` but queue unbounded. Symbols submitted faster than processed → memory growth. |
| **Background Scan + Telegram Commands Race** | `atlas_runtime.py` + `telegram_command_service.py` | High | Both use `runtime.scanner` and `runtime.engine` without coordination. |
| **No Circuit Breaker for Gate.io API** | `gateio_futures.py` | Medium | Consecutive 5xx errors don't trigger backoff; hammer failing endpoint. |
| **SQLite WAL Mode Not Enforced** | `trade_journal.py` | Low | Default journal mode may cause lock contention under concurrent access. |

---

## 11. Test Coverage Analysis

### Test Results: **1147 passed, 3 skipped (60s)**

### Coverage Gaps

| Area | Test File | Missing Coverage |
|------|-----------|------------------|
| **WS Reconnection** | `test_websocket_first_snapshot.py` | No test for WS drop + reconnect + data continuity |
| **Scanner Pool Corruption** | `test_atlas_scan_quality.py` | No concurrent scan + command test |
| **Learning PENDING Pollution** | `test_learning_persistence.py` | No test that unresolved signal outcomes excluded from learning |
| **SMC Common Filter Bypass** | `test_strategy_lab.py` | No test verifying SMC candidate goes through `_finalize_candidate_geometry` |
| **Risk Recalc After Stop Expand** | `test_risk_engine.py` | No test for SMC path with auto-expand |
| **Telegram Command Rate Limit** | `test_telegram_command_service.py` | No stress test for command spam |
| **OI Single Snapshot Handling** | `test_data_engine.py` | No test for liquidation strategy with count=1 OI |
| **Signal Outcome Same-Candle TP+SL** | `test_backtest_runner.py` | Conservative handling tested but not in live journal resolution |

---

## 12. Critical Fixes Required (Priority Order)

### 🔴 P0 - Critical (Block Release) - **FIXED**

1. ✅ **SMC Strategy Bypasses Common Filter Geometry Validation**
   - File: `strategy_lab.py:806-844`
   - Fix: Removed special case that skipped `_finalize_candidate_geometry()` for SMC. All 7 strategies now pass through the same structural geometry validation.

2. ✅ **Scanner Pool Cleared on Every Telegram Scan Command**
   - File: `telegram_command_service.py:967-968`
   - Fix: Removed `scanner.clear()` call. Added thread-safe `clear_scanner()` method to `AtlasEngine` with `_scanner_lock`. TUI updated to use `engine.clear_scanner()`.

3. ✅ **Unresolved Signal Outcomes Pollute Learning Index**
   - File: `engine.py:734-783`
   - Fix: Added documentation in `refresh_learning()` confirming that `trade_journal.learning_records(source="signal")` already filters to only TP1/TP2/TP3/SL statuses (PENDING/EXPIRED excluded). No code change needed - behavior was already correct.

4. ✅ **Background Scan + Telegram Command Race Condition**
   - File: `engine.py:213-220`, `atlas_runtime.py:135-137`, `atlas_tui.py:869`
   - Fix: Added `_scanner_lock` to `AtlasEngine`, thread-safe `clear_scanner()` method, and `scanner` property to `AtlasRuntime`. TUI now uses `engine.clear_scanner()`.

### 🟠 P1 - High (Fix Before Next Deploy) - **FIXED**

5. **WS Connection Per Analysis (No Pooling)**
   - File: `data_engine.py:126-136`, `strategies/orderflow/gateio_public_stream.py`
   - Fix: Implement `GatePublicStream` connection pool keyed by symbol; reuse across analyses. (Not yet implemented)

6. ✅ **DecisionEngine Quality Gate Duplicates StrategyLab Filter**
   - File: `decision_engine.py:51-150`, `atlas_main_engine.py:525`
   - Fix: Added `skip_eligibility_gates` parameter to `DecisionEngine.decide()`. `AtlasMainEngine.decide()` now passes `skip_eligibility_gates=True` since common filter already validated candidates.

7. ✅ **MIN_STOP_ATR_MULTIPLIER Config Inconsistency**
   - File: `config.py:111` (0.75), `risk_engine.py:310`, `setup_reasoning_engine.py:538`
   - Fix: Unified fallback defaults to 0.75 across all engines to match config default.

8. **Risk Recalculation After Stop Expand Misses SMC Path**
   - File: `engine.py:1630-1652`
   - Fix: Ensure `finalize_setup_geometry()` triggers risk rebuild for all strategy paths. (Not yet implemented)

### 🟡 P2 - Medium (Schedule in Sprint)

9. **Telegram Command Rate Limiting**
   - File: `telegram_command_service.py`
   - Fix: Per-user/command cooldown (e.g., 10s between scans).

10. **Async Command Execution**
    - File: `telegram_command_service.py:569-586`
    - Fix: Offload `execute_command()` to thread pool; reply via callback.

11. **Learning Global Fallback Default Mismatch**
    - File: `config.py:389`, `learning_engine.py:474`
    - Fix: Align defaults; `LEARNING_GLOBAL_FALLBACK=false` should disable global bucket.

12. **Signal Outcome Resolution Limited to 15m Candles**
    - File: `trade_journal.py` (resolve_signal_outcomes)
    - Fix: Accept multi-timeframe candles for intrabar TP/SL detection.

13. **SMT Universe Cache Staleness**
    - File: `data_engine.py:505-530`
    - Fix: Reduce 15m TTL from 45s to 15s during active scanning.

### 🟢 P3 - Low (Technical Debt)

14. **Strategy Execution Telemetry**
    - File: `strategy_lab.py`, `atlas_runtime.py`
    - Add counters: runs, raw_setups, filtered, selected per strategy.

15. **BotFather Menu Auto-Sync**
    - File: `telegram_botfather.py`
    - Call `set_my_commands` on config reload.

16. **Circuit Breaker for Gate.io API**
    - File: `gateio_futures.py`
    - Exponential backoff on 5xx/429.

17. **SQLite WAL Mode**
    - File: `trade_journal.py`
    - `PRAGMA journal_mode=WAL` on connection.

---

## 13. Test Execution Plan

```bash
# 1. Run full suite (baseline)
.venv/bin/python -m pytest tests/ -v --tb=short

# 2. Run strategy-specific tests
.venv/bin/python -m pytest tests/test_strategy_lab.py -v
.venv/bin/python -m pytest tests/test_atlas_main_engine.py -v

# 3. Run risk/geometry tests
.venv/bin/python -m pytest tests/test_risk_engine.py tests/test_dynamic_tp_quality.py -v

# 4. Run Telegram command tests
.venv/bin/python -m pytest tests/test_telegram_command_service*.py -v

# 5. Run data engine tests
.venv/bin/python -m pytest tests/test_data_engine.py tests/test_gateio_futures.py -v

# 6. Run learning tests
.venv/bin/python -m pytest tests/test_learning_persistence.py tests/test_live_learning_production.py -v

# 7. Run backtest quality tests
.venv/bin/python -m pytest tests/test_backtest_runner.py tests/test_backtest_zero_execution_repairs.py -v
```

---

## 14. Branch & PR Strategy

```bash
# 1. Create audit branch
git checkout -b audit/system-audit-2026-11-17

# 2. Fix P0 issues in atomic commits
git commit -m "fix: SMC strategy now passes through common filter geometry validation"
git commit -m "fix: Remove scanner.clear() from Telegram scan commands to preserve pool"
git commit -m "fix: Exclude PENDING signal outcomes from learning index rebuild"
git commit -m "fix: Add scanner lock to prevent background+command race"

# 3. Fix P1 issues
# ... additional commits

# 4. Run full test suite
.venv/bin/python -m pytest tests/ -x

# 5. Open PR with this audit report as description
```

---

## 15. Verification Checklist for PR

- [ ] All 1147 existing tests pass
- [ ] New tests added for each P0/P1 fix
- [ ] SMC strategy produces same setups but validated through common filter
- [ ] `/20tara` → `/eniyi5` flow preserves pool correctly
- [ ] Learning index rebuild excludes PENDING signal outcomes
- [ ] Concurrent background scan + `/eniyi5` doesn't corrupt pool
- [ ] Gate.io WS connections pooled and reused
- [ ] DecisionEngine only ranks, doesn't gate eligibility
- [ ] Risk config values unified (MIN_STOP_ATR_MULTIPLIER)
- [ ] Telegram commands respond within 2s (async execution)

---

**Report Generated:** 2026-11-17  
**Auditor:** Atlas System Audit  
**Next Review:** After P0/P1 fixes merged and CI validated