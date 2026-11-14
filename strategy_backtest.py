"""Historical replay for all seven independent Atlas strategies.

Signals are evaluated only on closed candles. Market candidates enter at the
next 15m open; limits must actually trade through the limit price. Intrabar
stop/target ambiguity is resolved conservatively in favor of the stop.
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
)
from engine import AtlasEngine
from strategy_lab import SevenStrategyLab
from strategy_outcome_journal import StrategyOutcomeJournal
from historical_derivatives import load_historical_derivatives
from microstructure_archive import snapshot_at as archived_microstructure_at


ENTRY_TIMEFRAME_MS = TIMEFRAME_DURATION_MS["15m"]
TP_WEIGHTS = (0.5, 0.3, 0.2)


def _closed_at(candle, timeframe):
    return int(candle.time) + TIMEFRAME_DURATION_MS[timeframe]


def _snapshot_at(history, index, entry_price):
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
    # This is the next bar's open, not a future candle close. It is the
    # executable reference for a signal confirmed at decision_ms.
    snapshot["current_price"] = float(entry_price)
    snapshot["current_price_source"] = "BACKTEST_NEXT_15M_OPEN"
    snapshot["current_price_timestamp_ms"] = int(candles_15m[index + 1].time)
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
                       funding_events=()):
    """Return a cost-adjusted outcome or None when a limit never fills."""
    direction = str(candidate.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return None
    try:
        planned_entry = float(candidate["entry"])
        stop = float(candidate["stop_loss"])
        targets = [float(candidate[key]) for key in ("tp1", "tp2", "tp3") if candidate.get(key) is not None]
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not targets or not all(math.isfinite(value) and value > 0 for value in [planned_entry, stop, *targets]):
        return None
    risk = planned_entry - stop if direction == "LONG" else stop - planned_entry
    if risk <= 0:
        return None
    if direction == "LONG":
        if not stop < planned_entry < targets[0] or any(a >= b for a, b in zip(targets, targets[1:])):
            return None
    else:
        if not targets[0] < planned_entry < stop or any(a <= b for a, b in zip(targets, targets[1:])):
            return None
    if not future_candles:
        return None

    entry_type = str(candidate.get("entry_type") or "MARKET").upper()
    fill_candle = future_candles[0]
    fill_open = float(fill_candle.open)
    if entry_type == "LIMIT":
        if not float(fill_candle.low) <= planned_entry <= float(fill_candle.high):
            return None
        entry = planned_entry
        entry_fee = maker_fee
    else:
        # Preserve stop/target distances when the next-bar open differs from
        # the reference price used to construct the signal.
        shift = fill_open - planned_entry
        entry = fill_open
        stop += shift
        targets = [value + shift for value in targets]
        risk = entry - stop if direction == "LONG" else stop - entry
        if risk <= 0:
            return None
        if direction == "LONG" and not stop < entry < targets[0]:
            return None
        if direction == "SHORT" and not targets[0] < entry < stop:
            return None
        entry_fee = taker_fee

    weights = list(TP_WEIGHTS[:len(targets)])
    if len(weights) < len(targets):
        weights.extend([0.0] * (len(targets) - len(weights)))
    weights[-1] += 1.0 - sum(weights)
    remaining = 1.0
    gross_r = 0.0
    exit_notional = 0.0
    exit_weight = 0.0
    stop_price = stop
    exit_index = None
    exit_reason = "TIME_EXIT"

    for offset, candle in enumerate(future_candles[:max_bars]):
        high, low, close = float(candle.high), float(candle.low), float(candle.close)
        stop_hit = low <= stop_price if direction == "LONG" else high >= stop_price
        target_hits = [
            index for index, target in enumerate(targets)
            if weights[index] > 0 and (
                high >= target if direction == "LONG" else low <= target
            )
        ]
        if stop_hit and target_hits:
            # Same candle touches both sides: adverse stop is assumed first.
            realized_weight = remaining
            gross_r += realized_weight * _directional_r(direction, entry, stop_price, risk)
            exit_notional += realized_weight * stop_price
            exit_weight += realized_weight
            remaining = 0.0
            exit_index = offset
            exit_reason = "STOP_AND_TARGET_SAME_BAR_STOP_FIRST"
            break
        if stop_hit:
            gross_r += remaining * _directional_r(direction, entry, stop_price, risk)
            exit_notional += remaining * stop_price
            exit_weight += remaining
            remaining = 0.0
            exit_index = offset
            exit_reason = "STOP"
            break
        for target_index in target_hits:
            weight = min(weights[target_index], remaining)
            if weight <= 0:
                continue
            target = targets[target_index]
            gross_r += weight * _directional_r(direction, entry, target, risk)
            exit_notional += weight * target
            exit_weight += weight
            remaining -= weight
            weights[target_index] = 0.0
            if target_index == 0 and remaining > 0:
                stop_price = entry
            if remaining <= 1e-9:
                remaining = 0.0
                exit_index = offset
                exit_reason = "ALL_TARGETS"
                break
        if remaining <= 1e-9:
            break

    if remaining > 1e-9:
        last_offset = min(max_bars, len(future_candles)) - 1
        last_candle = future_candles[last_offset]
        exit_price = float(last_candle.close)
        gross_r += remaining * _directional_r(direction, entry, exit_price, risk)
        exit_notional += remaining * exit_price
        exit_weight += remaining
        exit_index = last_offset
    average_exit = exit_notional / max(exit_weight, 1e-12)
    trading_cost_r = (
        entry * entry_fee
        + entry * spread_rate
        + entry * slippage_rate
        + average_exit * taker_fee
        + average_exit * spread_rate
        + average_exit * slippage_rate
    ) / risk
    closed_candle = future_candles[exit_index or 0]
    entry_time_ms = int(fill_candle.time)
    exit_time_ms = _closed_at(closed_candle, "15m")
    funding_pnl = 0.0
    for event in funding_events or ():
        try:
            event_ms = int(event.get("timestamp") or 0)
            rate = float(event.get("value"))
        except (TypeError, ValueError, OverflowError, AttributeError):
            continue
        if not (entry_time_ms < event_ms <= exit_time_ms) or not math.isfinite(rate):
            continue
        mark = entry
        for candle in future_candles[:(exit_index or 0) + 1]:
            if int(candle.time) <= event_ms <= _closed_at(candle, "15m"):
                mark = float(candle.close)
                break
        # Count only funding cash outflows. Credits are ignored because
        # intrabar position size at settlement is ambiguous in OHLCV replay.
        cashflow_r = (-1.0 if direction == "LONG" else 1.0) * rate * mark / risk
        funding_pnl += min(0.0, cashflow_r)
    cost_r = trading_cost_r - funding_pnl
    net_r = gross_r - cost_r
    return {
        "gross_r": round(gross_r, 8),
        "trading_cost_r": round(trading_cost_r, 8),
        "funding_pnl_r": round(funding_pnl, 8),
        "cost_r": round(cost_r, 8),
        "net_r": round(net_r, 8),
        "entry": round(entry, 10),
        "stop_loss": round(stop, 10),
        "average_exit": round(average_exit, 10),
        "exit_reason": exit_reason,
        "bars_held": int(exit_index or 0) + 1,
        "closed_at_ms": _closed_at(closed_candle, "15m"),
        "cost_model_id": (
            f"fee{maker_fee:.6f}-{taker_fee:.6f}_spread{spread_rate:.6f}_"
            f"slip{slippage_rate:.6f}_funding_historical_partial50-30-20_v2"
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
                                maker_fee=0.0002, taker_fee=0.00055,
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
        symbol, days, step, max_holding_bars, maker_fee, taker_fee,
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
        next_open = float(candles[index + 1].open)
        snapshot = _snapshot_at(history, index, next_open)
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
            future = candles[index + 1:index + 1 + max_holding_bars]
            outcome = simulate_candidate(
                candidate, future,
                maker_fee=maker_fee, taker_fee=taker_fee,
                spread_rate=spread_rate, slippage_rate=slippage_rate,
                max_bars=max_holding_bars,
                funding_events=history.get("funding_records") or [],
            )
            if outcome is None:
                continue
            fill_time = int(candles[index + 1].time)
            split = "is" if fill_time < is_cutoff else "oos"
            active_until[strategy_id] = index + outcome["bars_held"]
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
    parser.add_argument("--persist", action="store_true", help="Doğrulanmış maliyet modeliyle IS/OOS sonuçlarını performans günlüğüne yaz")
    args = parser.parse_args()
    if args.days <= 0 or args.step <= 0 or args.max_holding_bars <= 0:
        parser.error("--days, --step ve --max-holding-bars pozitif olmalı")
    report = run_seven_strategy_backtest(
        args.symbol, days=args.days, step=args.step,
        max_holding_bars=args.max_holding_bars,
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
