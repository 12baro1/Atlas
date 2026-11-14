"""Historical replay for all seven independent Atlas strategies.

Signals are evaluated only on closed candles. Market candidates enter at the
next 15m open; limits fill only on touch, with gap-through fills treated as
marketable limits. Intrabar stop/target ambiguity is resolved stop-first.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import time
from collections import defaultdict

from backtest import (
    TIMEFRAME_DURATION_MS,
    _disable_backtest_live_features,
    attach_historical_smt_universe,
    load_historical,
    _effective_now_ms,
    _validate_backtest_coverage,
    _validate_backtest_history,
    _configured_partial_tp_weights,
)
from engine import AtlasEngine
from strategy_lab import SevenStrategyLab
from strategy_outcome_journal import StrategyOutcomeJournal
from historical_derivatives import load_historical_derivatives
from microstructure_archive import snapshot_at as archived_microstructure_at
from backtest_runner import simulate_trade_partial, market_fallback_check
from execution_costs import realized_trade_cost, adverse_funding_cost_r


ENTRY_TIMEFRAME_MS = TIMEFRAME_DURATION_MS["15m"]


def _closed_at(candle, timeframe):
    return int(candle.time) + TIMEFRAME_DURATION_MS[timeframe]


def _snapshot_at(history, index):
    candles_15m = history.get("15m") or []
    decision_candle = candles_15m[index]
    decision_ms = _closed_at(decision_candle, "15m")
    snapshot = {"symbol": history.get("symbol")}
    for timeframe, duration in TIMEFRAME_DURATION_MS.items():
        available = history.get(timeframe) or []
        if timeframe == "15m":
            snapshot[timeframe] = available[: index + 1]
        else:
            snapshot[timeframe] = [item for item in available if item.time + duration <= decision_ms]
    universe = {}
    for full_symbol, frames in (history.get("smt_universe") or {}).items():
        key = str(full_symbol).split("/", 1)[0].upper()
        if key in {"BTC", "ETH"}:
            universe[key] = [
                item for item in (frames.get("4h") or [])
                if item.time + TIMEFRAME_DURATION_MS["4h"] <= decision_ms
            ]
    snapshot["correlation_universe"] = universe
    snapshot["smt_universe"] = {
        full_symbol: {
            timeframe: [
                item for item in (frames.get(timeframe) or [])
                if item.time + TIMEFRAME_DURATION_MS[timeframe] <= decision_ms
            ]
            for timeframe in ("15m", "1h", "4h", "1d")
        }
        for full_symbol, frames in (history.get("smt_universe") or {}).items()
    }
    snapshot["sector_peer_universe"] = {
        peer_symbol: {
            "4h": [
                item for item in (frames.get("4h") or [])
                if item.time + TIMEFRAME_DURATION_MS["4h"] <= decision_ms
            ]
        }
        for peer_symbol, frames in (history.get("sector_peer_universe") or {}).items()
    }
    # The decision sees only the last closed candle. The next 15m open is
    # used by the fill simulator, never by the decision engine.
    snapshot["current_price"] = float(decision_candle.close)
    snapshot["current_price_source"] = "BACKTEST_DECISION_15M_CLOSE"
    snapshot["current_price_timestamp_ms"] = decision_ms
    snapshot["snapshot_timestamp_ms"] = decision_ms
    # Historical derivatives are timestamp-filtered to prevent look-ahead.
    oi_rows = [
        item for item in (history.get("open_interest_records") or [])
        if int(item.get("timestamp") or 0) <= decision_ms
    ]
    funding_rows = [
        item for item in (history.get("funding_records") or [])
        if int(item.get("timestamp") or 0) <= decision_ms
    ]
    snapshot["open_interest"] = [float(item["value"]) for item in oi_rows]
    snapshot["open_interest_timestamps_ms"] = [int(item["timestamp"]) for item in oi_rows]
    snapshot["funding_rate"] = [float(item["value"]) for item in funding_rows]
    snapshot["funding_rate_timestamps_ms"] = [int(item["timestamp"]) for item in funding_rows]
    # Archived book/trade snapshots are only usable if they existed before the
    # decision close and are fresh enough. No current snapshot is backfilled.
    micro = archived_microstructure_at(history.get("symbol"), decision_ms)
    if micro:
        snapshot.update(micro)
    else:
        snapshot["orderbook"] = None
        snapshot["recent_trades"] = None
        snapshot["orderbook_timestamp_ms"] = None
        snapshot["recent_trades_timestamp_ms"] = None
    return snapshot


def _directional_r(direction, entry, exit_price, risk):
    move = exit_price - entry if direction == "LONG" else entry - exit_price
    return move / risk


def simulate_candidate(candidate, future_candles, *, maker_fee=0.0002, taker_fee=0.00055,
                       spread_rate=0.0002, slippage_rate=0.0003, max_bars=32,
                       limit_expiry_bars=8, funding_events=()):
    """Replay a selected plan through the same fill/exit/cost contract as SMC backtest."""
    direction = str(candidate.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"} or not future_candles:
        return None
    try:
        planned_entry = float(candidate["entry"])
        stop = float(candidate["stop_loss"])
        targets = [float(candidate[key]) for key in ("tp1", "tp2", "tp3") if candidate.get(key) is not None]
        max_bars = max(1, int(max_bars))
        fill_open = float(future_candles[0].open)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not targets or not all(math.isfinite(value) and value > 0 for value in [planned_entry, stop, *targets, fill_open]):
        return None
    if direction == "LONG":
        if not stop < planned_entry < targets[0] or any(a >= b for a, b in zip(targets, targets[1:])):
            return None
    else:
        if not targets[0] < planned_entry < stop or any(a <= b for a, b in zip(targets, targets[1:])):
            return None

    planned_type = str(candidate.get("entry_type") or "MARKET").upper()
    simulation_start_offset = 0
    fill_index = 0
    if planned_type == "LIMIT":
        fill_index = None
        for candidate_index, candidate_candle in enumerate(future_candles[:max(1, int(limit_expiry_bars))]):
            candidate_open = float(candidate_candle.open)
            marketable = (direction == "LONG" and candidate_open <= planned_entry) or (direction == "SHORT" and candidate_open >= planned_entry)
            touched = (float(candidate_candle.low) <= planned_entry) if direction == "LONG" else (float(candidate_candle.high) >= planned_entry)
            if marketable:
                fill_index = candidate_index
                fill_candle = candidate_candle
                fill_open = candidate_open
                entry = fill_open
                entry_type = "MARKETABLE_LIMIT"
                simulation_start_offset = candidate_index
                simulation_candles = future_candles[candidate_index:candidate_index + max_bars]
                simulation_horizon = max_bars
                break
            if touched:
                fill_index = candidate_index
                fill_candle = candidate_candle
                fill_open = candidate_open
                entry = planned_entry
                entry_type = "LIMIT"
                fill_stop_hit = (float(fill_candle.low) <= stop) if direction == "LONG" else (float(fill_candle.high) >= stop)
                if fill_stop_hit:
                    simulation_start_offset = candidate_index
                    simulation_candles = future_candles[candidate_index:candidate_index + 1]
                    simulation_horizon = 1
                else:
                    simulation_start_offset = candidate_index + 1
                    simulation_candles = future_candles[candidate_index + 1:candidate_index + max_bars]
                    simulation_horizon = max(1, max_bars - 1)
                break
            fallback_ok, _, _ = market_fallback_check(
                candidate_open, planned_entry, stop, targets[0], direction,
                {"atr": candidate.get("atr")}, maker_fee_rate=maker_fee,
                taker_fee_rate=taker_fee, spread_rate=spread_rate, slippage_rate=slippage_rate,
            )
            if fallback_ok:
                fill_index = candidate_index
                fill_candle = candidate_candle
                fill_open = candidate_open
                entry = fill_open
                entry_type = "MARKET_FALLBACK"
                simulation_start_offset = candidate_index
                simulation_candles = future_candles[candidate_index:candidate_index + max_bars]
                simulation_horizon = max_bars
                break
        if fill_index is None:
            return None
    elif planned_type == "MARKET":
        fill_index = 0
        fill_candle = future_candles[0]
        fill_open = float(fill_candle.open)
        entry = fill_open
        entry_type = "MARKET"
        shift = fill_open - planned_entry
        stop += shift
        targets = [value + shift for value in targets]
        simulation_start_offset = 0
        simulation_candles = future_candles[:max_bars]
        simulation_horizon = max_bars
    else:
        return None

    if direction == "LONG":
        if not stop < entry < targets[0] or any(a >= b for a, b in zip(targets, targets[1:])):
            return None
    else:
        if not targets[0] < entry < stop or any(a <= b for a, b in zip(targets, targets[1:])):
            return None
    risk = entry - stop if direction == "LONG" else stop - entry
    if risk <= 0 or not simulation_candles:
        return None

    tp_weights = candidate.get("partial_exit_weights") or _configured_partial_tp_weights()
    outcome = simulate_trade_partial(
        entry=entry, stop_loss=stop, targets=targets,
        future_candles=simulation_candles, direction=direction,
        tp_weights=tp_weights, max_holding_bars=simulation_horizon,
    )
    if outcome.get("result") == "OPEN" or outcome.get("exit_offset") is None:
        return None
    full_exit_index = simulation_start_offset + int(outcome["exit_offset"])
    if full_exit_index >= len(future_candles):
        return None
    closed_candle = future_candles[full_exit_index]
    exit_price = float(outcome["exit_price"])
    gross_r = float(outcome["net_rr"])
    cost_parts = realized_trade_cost(
        entry_price=entry, exit_price=exit_price, entry_type=entry_type,
        exit_reason=outcome.get("exit_reason"), targets=targets,
        reached_levels=outcome.get("levels") or [], tp_weights=tp_weights,
        partial_exits=True, maker_fee_rate=maker_fee, taker_fee_rate=taker_fee,
        spread_rate=spread_rate, slippage_rate=slippage_rate,
    )
    trading_cost_r = float(cost_parts["total"]) / risk
    entry_time_ms = int(fill_candle.time)
    exit_time_ms = _closed_at(closed_candle, "15m")
    funding = adverse_funding_cost_r(
        direction, entry, risk, entry_time_ms, exit_time_ms,
        candles=future_candles[:full_exit_index + 1],
        funding_records=funding_events, timeframe_ms=ENTRY_TIMEFRAME_MS,
    )
    funding_pnl = funding["funding_pnl_r"]
    cost_r = trading_cost_r + funding["funding_cost_r"]
    net_r = gross_r - cost_r
    weight_label = "-".join(str(round(float(tp_weights.get("tp" + str(i), 0.0)), 2)) for i in (1, 2, 3))
    return {
        "gross_r": round(gross_r, 8), "trading_cost_r": round(trading_cost_r, 8),
        "funding_pnl_r": round(funding_pnl, 8), "funding_cost_r": funding["funding_cost_r"],
        "funding_events_charged": funding["charged_events"],
        "cost_r": round(cost_r, 8), "net_r": round(net_r, 8),
        "entry": round(entry, 10), "entry_type": entry_type,
        "stop_loss": round(stop, 10), "average_exit": outcome.get("average_exit"),
        "exit_reason": outcome.get("exit_reason"),
        "fill_time_ms": entry_time_ms, "fill_offset": fill_index,
        "bars_held": full_exit_index - fill_index + 1,
        "bars_until_exit": full_exit_index + 1, "closed_at_ms": exit_time_ms,
        "cost_model_id": (
            f"shared_fill_partial{weight_label}_maker{maker_fee:.6f}_taker{taker_fee:.6f}_"
            f"spread{spread_rate:.6f}_slip{slippage_rate:.6f}_adverse_funding_v3"
        ),
    }


def _summarize(rows):
    values = [float(item["net_r"]) for item in rows]
    winners = [value for value in values if value > 0]
    losers = [-value for value in values if value < 0]
    count = len(values)
    return {
        "trades": count,
        "win_rate_pct": round(100.0 * len(winners) / count, 2) if count else 0.0,
        "net_expectancy_r": round(sum(values) / count, 4) if count else 0.0,
        "net_profit_factor": round(sum(winners) / sum(losers), 4) if losers else (999.0 if winners else 0.0),
        "net_r": round(sum(values), 4),
        "average_cost_r": round(sum(float(item["cost_r"]) for item in rows) / count, 4) if count else 0.0,
    }



def _walk_forward_summary(rows, start_ms, end_ms, folds=5):
    """Anchored expanding-window validation with sequential untouched test folds."""
    span = max(0, int(end_ms) - int(start_ms))
    if span <= 0 or folds < 2:
        return []
    test_width = span / (folds + 1)
    output = []
    for fold_index in range(folds):
        test_start = int(start_ms + test_width * (fold_index + 1))
        test_end = int(start_ms + test_width * (fold_index + 2))
        train = [row for row in rows if int(row.get("closed_at_ms") or 0) < test_start]
        test = [
            row for row in rows
            if test_start <= int(row.get("closed_at_ms") or 0) < test_end
        ]
        output.append({
            "fold": fold_index + 1,
            "train_start_ms": int(start_ms),
            "train_end_ms": test_start,
            "test_start_ms": test_start,
            "test_end_ms": test_end,
            "train": _summarize(train),
            "test": _summarize(test),
        })
    return output

def run_seven_strategy_backtest(symbol, days=30, step=1, max_holding_bars=32,
                                limit_expiry_bars=8, maker_fee=0.0002, taker_fee=0.00055,
                                spread_rate=0.0002, slippage_rate=0.0003,
                                persist_outcomes=False):
    _disable_backtest_live_features()
    now_ms = int(time.time() * 1000)
    history = load_historical(symbol, days=days, now_ms=now_ms)
    _validate_backtest_history(history, symbol)
    effective_now = _effective_now_ms(history)
    _validate_backtest_coverage(history, symbol, days, effective_now)
    attach_historical_smt_universe(history, days, effective_now)
    candles = history.get("15m") or []
    if len(candles) < 320:
        raise RuntimeError(f"{symbol}: yetersiz 15m warmup ({len(candles)} mum).")
    derivatives = load_historical_derivatives(
        symbol, int(candles[0].time), int(candles[-1].time) + ENTRY_TIMEFRAME_MS
    )
    history.update(derivatives)
    # Split only the actually evaluable interval. This avoids pretending that
    # a provider-limited 1,000-candle history covers the full requested horizon.
    evaluation_start = max(now_ms - int(days * 86_400_000), _closed_at(candles[300], "15m"))
    evaluation_end = _closed_at(candles[-2], "15m")
    if evaluation_end <= evaluation_start:
        raise RuntimeError(f"{symbol}: IS/OOS için yeterli değerlendirme aralığı yok.")
    is_cutoff = evaluation_start + int((evaluation_end - evaluation_start) * 0.70)

    engine = AtlasEngine()
    lab = SevenStrategyLab()
    journal = StrategyOutcomeJournal()
    revision = journal.current_revision()
    replay_fingerprint = "|".join(map(str, (
        symbol, days, step, max_holding_bars, limit_expiry_bars, maker_fee, taker_fee,
        spread_rate, slippage_rate, revision, evaluation_start, is_cutoff,
    )))
    run_id = hashlib.sha256(replay_fingerprint.encode("utf-8")).hexdigest()
    run_created_at_ms = int(time.time() * 1000)
    funding_available = (history.get("derivatives_data_quality") or {}).get("funding") == "HISTORICAL"
    persistence_enabled = bool(persist_outcomes and funding_available)
    persistence_block_reason = None
    if persist_outcomes and not funding_available:
        persistence_block_reason = "Historical funding series unavailable; cost-complete outcomes were not persisted."
    all_outcomes = defaultdict(list)
    active_until = {}
    calls = 0
    for index in range(300, len(candles) - 1, max(1, int(step))):
        decision_ms = _closed_at(candles[index], "15m")
        if decision_ms < evaluation_start:
            continue
        snapshot = _snapshot_at(history, index)
        try:
            smc_result = engine.analyze(snapshot)
        except Exception:
            # Keep the six independent evaluators alive if a legacy SMC replay
            # step encounters an isolated historical-data edge case.
            smc_result = None
        report = lab.analyze(snapshot, smc_result=smc_result)
        calls += 1
        for candidate in report.get("strategies") or []:
            if candidate.get("status") != "CANDIDATE":
                continue
            strategy_id = candidate["strategy_id"]
            if index <= active_until.get(strategy_id, -1):
                continue
            future = candles[index + 1:index + 1 + max_holding_bars + limit_expiry_bars]
            outcome = simulate_candidate(
                candidate, future,
                maker_fee=maker_fee, taker_fee=taker_fee,
                spread_rate=spread_rate, slippage_rate=slippage_rate,
                max_bars=max_holding_bars,
                limit_expiry_bars=limit_expiry_bars,
                funding_events=history.get("funding_records") or [],
            )
            if outcome is None:
                continue
            fill_time = int(outcome["fill_time_ms"])
            split = "is" if fill_time < is_cutoff else "oos"
            active_until[strategy_id] = index + outcome["bars_until_exit"]
            record = {
                **outcome,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "split": split,
                "signal_time_ms": decision_ms,
                "regime": (report.get("regime") or {}).get("label", "UNKNOWN"),
            }
            all_outcomes[strategy_id].append(record)
            if persistence_enabled:
                trade_id = f"{run_id}|{strategy_id}|{fill_time}"
                journal.record_outcome(
                    strategy_id=strategy_id,
                    trade_id=trade_id,
                    run_id=run_id,
                    run_created_at_ms=run_created_at_ms,
                    split=split,
                    net_r=outcome["net_r"],
                    gross_r=outcome["gross_r"],
                    cost_r=outcome["cost_r"],
                    funding_pnl_r=outcome["funding_pnl_r"],
                    cost_model_id=outcome["cost_model_id"],
                    closed_at_ms=outcome["closed_at_ms"],
                    costs_included=True,
                    symbol=symbol,
                    source_revision=revision,
                    regime=record["regime"],
                )

    results = {}
    for strategy_id in (
        "trend_pullback", "volatility_breakout", "mean_reversion",
        "liquidation_cascade", "orderflow_momentum", "relative_strength", "smc",
    ):
        rows = all_outcomes.get(strategy_id, [])
        results[strategy_id] = {
            "IS": _summarize([item for item in rows if item["split"] == "is"]),
            "OOS": _summarize([item for item in rows if item["split"] == "oos"]),
            "all": _summarize(rows),
            "trades": rows,
            "walk_forward": _walk_forward_summary(rows, evaluation_start, evaluation_end),
        }
    return {
        "symbol": symbol,
        "days": days,
        "effective_days": round((evaluation_end - evaluation_start) / 86_400_000, 2),
        "analysis_calls": calls,
        "evaluation_start_ms": evaluation_start,
        "is_cutoff_ms": is_cutoff,
        "results": results,
        "performance_records": journal.performance_snapshot(
            symbol=symbol,
            source_revision=revision,
            run_id=run_id,
        ),
        "derivatives_data_quality": history.get("derivatives_data_quality") or {},
        "microstructure_archive": "LOCAL_TIMESTAMPED_ARCHIVE_ONLY",
        "persistence_enabled": persistence_enabled,
        "persistence_block_reason": persistence_block_reason,
        "historical_data_limitations": [
            "Walk-forward uses anchored expanding training windows and sequential test folds; it does not auto-tune parameters.",
            "Funding costs are applied only at historical settlement timestamps returned by the exchange; if funding history is unavailable, outcomes must not be treated as fully cost-complete.",
            "Order-flow replay requires previously archived timestamped order-book/trade snapshots. No historical book is fabricated or backfilled.",
            "Liquidation cascade uses historical OI/funding plus archived trade flow where available; it remains a proxy, not an exchange liquidation-event feed.",
            "Fees, spread and slippage remain configurable execution assumptions, not actual exchange fills.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Atlas 7 strateji tarihsel replay")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--step", type=int, default=1, help="Her kaç 15m mumda bir analiz")
    parser.add_argument("--max-holding-bars", type=int, default=32)
    parser.add_argument("--limit-expiry-bars", type=int, default=8)
    parser.add_argument("--persist", action="store_true", help="Doğrulanmış maliyet modeliyle IS/OOS sonuçlarını performans günlüğüne yaz")
    args = parser.parse_args()
    if args.days <= 0 or args.step <= 0 or args.max_holding_bars <= 0 or args.limit_expiry_bars <= 0:
        parser.error("--days, --step, --max-holding-bars ve --limit-expiry-bars pozitif olmalı")
    report = run_seven_strategy_backtest(
        args.symbol, days=args.days, step=args.step,
        max_holding_bars=args.max_holding_bars,
        limit_expiry_bars=args.limit_expiry_bars,
        persist_outcomes=args.persist,
    )
    print(
        f"7 STRATEJİ BACKTEST | {report['symbol']} | istenen={report['days']} gün | "
        f"gerçekleşen={report['effective_days']} gün | analiz={report['analysis_calls']}"
    )
    print(f"{'STRATEJİ':<24} {'BÖLÜM':<5} {'İŞLEM':>6} {'WR':>8} {'PF':>8} {'EXP R':>9} {'NET R':>9}")
    for strategy_id, payload in report["results"].items():
        for split in ("IS", "OOS"):
            item = payload[split]
            print(
                f"{strategy_id:<24} {split:<5} {item['trades']:>6} "
                f"{item['win_rate_pct']:>7.2f}% {item['net_profit_factor']:>8.3f} "
                f"{item['net_expectancy_r']:>9.4f} {item['net_r']:>9.3f}"
            )
    if report.get("persistence_block_reason"):
        print(f"KAYIT ENGELLENDİ | {report['persistence_block_reason']}")
    for strategy_id, payload in report["results"].items():
        print(f"WALK-FORWARD | {strategy_id}")
        for fold in payload["walk_forward"]:
            test = fold["test"]
            print(
                f"  Fold {fold['fold']}: test={test['trades']} işlem "
                f"EXP={test['net_expectancy_r']:.4f}R PF={test['net_profit_factor']:.3f}"
            )
    for note in report["historical_data_limitations"]:
        print(f"VERİ SINIRI | {note}")


if __name__ == "__main__":
    main()
