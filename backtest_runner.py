"""
backtest_runner.py
Atlas için GERÇEK bir backtest çerçevesi.

Mevcut BacktestEngine sadece elle kaydedilen trade'lerin istatistiklerini toplar.
Bu motor ise sinyali FİYAT GEÇMİŞİNDE oynatır:
  1. Tarihsel mumları adım adım ileri kaydırarak engine.analyze() çağırır.
  2. Uygulanabilir bir sinyal üretildiğinde entry/stop/TP seviyelerini alır.
  3. Müteakip mumlarda SL'ye mi yoksa TP1/TP2/TP3'e mi ÖNCÜ vuruş olduğunu okurak sonucu kaydeder.
  4. Fee/spread dahil expectancy, winrate, profit factor raporlar.

Amacı: "Bu sinyal filtresi gerçekten edge (beklenti) üretiyor mu?" sorusunu yanıtlamak.
"""

import logging
import math

from config import Config
from execution_costs import estimate_plan_cost, realized_trade_cost, adverse_funding_cost_r

logger = logging.getLogger("atlas.backtest_runner")


def _num(value, digits=4):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _tps(targets):
    """targets: dict ya da [tp1, tp2, tp3] liste. (tp1, tp2, tp3) döndürür."""
    if isinstance(targets, dict):
        return (
            _num(targets.get("tp1")),
            _num(targets.get("tp2")),
            _num(targets.get("tp3")),
        )
    if isinstance(targets, (list, tuple)):
        values = [_num(t) for t in targets]
        while len(values) < 3:
            values.append(None)
        return values[0], values[1], values[2]
    return None, None, None


def simulate_trade(entry, stop_loss, targets, future_candles, direction="LONG", round_trip_cost_rate=0.002, max_holding_bars=None):
    """Simulate one full exit; optionally close at the shared max-holding horizon."""
    direction = (direction or "LONG").upper()
    entry = _num(entry)
    stop = _num(stop_loss)
    tp1, tp2, tp3 = _tps(targets)
    levels = [(level_no, target) for level_no, target in enumerate((tp1, tp2, tp3), start=1) if target is not None]
    if entry is None or stop is None or not future_candles or not levels:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}
    is_long = direction in ("LONG", "BUY")
    bars = list(future_candles)
    horizon = max(1, int(max_holding_bars)) if max_holding_bars is not None else None
    simulation_bars = bars[:horizon] if horizon is not None else bars
    for offset, candle in enumerate(simulation_bars):
        low, high = candle.low, candle.high
        opened = _num(getattr(candle, "open", None))
        if is_long:
            if low <= stop:
                gap = opened is not None and opened <= stop
                exit_price = opened if gap else stop
                realized_r = (exit_price - entry) / risk_distance
                gap_distance = max(0.0, stop - exit_price) if gap else 0.0
                return {"result": "LOSS", "tp": 0, "net_rr": _num(realized_r), "exit_reason": "STOP", "exit_offset": offset, "exit_price": exit_price, "stop_gap": gap, "stop_gap_distance": _num(gap_distance), "stop_gap_r": _num(gap_distance / risk_distance)}
            for level_no, target in levels:
                if high >= target:
                    rr = abs(target - entry) / risk_distance
                    return {"result": "WIN", "tp": level_no, "net_rr": _num(rr), "exit_reason": f"TP{level_no}", "exit_offset": offset, "exit_price": target, "stop_gap": False, "stop_gap_distance": 0.0, "stop_gap_r": 0.0}
        else:
            if high >= stop:
                gap = opened is not None and opened >= stop
                exit_price = opened if gap else stop
                realized_r = (entry - exit_price) / risk_distance
                gap_distance = max(0.0, exit_price - stop) if gap else 0.0
                return {"result": "LOSS", "tp": 0, "net_rr": _num(realized_r), "exit_reason": "STOP", "exit_offset": offset, "exit_price": exit_price, "stop_gap": gap, "stop_gap_distance": _num(gap_distance), "stop_gap_r": _num(gap_distance / risk_distance)}
            for level_no, target in levels:
                if low <= target:
                    rr = abs(entry - target) / risk_distance
                    return {"result": "WIN", "tp": level_no, "net_rr": _num(rr), "exit_reason": f"TP{level_no}", "exit_offset": offset, "exit_price": target, "stop_gap": False, "stop_gap_distance": 0.0, "stop_gap_r": 0.0}
    if horizon is not None and len(simulation_bars) >= horizon:
        last = simulation_bars[-1]
        exit_price = _num(last.close)
        if exit_price is not None:
            realized_r = (exit_price - entry) / risk_distance if is_long else (entry - exit_price) / risk_distance
            return {"result": "WIN" if realized_r > 0 else "LOSS", "tp": 0, "net_rr": _num(realized_r), "exit_reason": "TIME_EXIT", "exit_offset": len(simulation_bars) - 1, "exit_price": exit_price, "stop_gap": False, "stop_gap_distance": 0.0, "stop_gap_r": 0.0}
    return {"result": "OPEN", "tp": 0, "net_rr": 0.0}


def _candle_touched_stop(is_long, stop, low, high):
    """Fiyat verilen stop seviyesine değdi mi? (long: low, short: high)"""
    if is_long:
        return low <= stop
    return high >= stop


def simulate_trade_partial(
    entry,
    stop_loss,
    targets,
    future_candles,
    direction="LONG",
    tp_weights=None,
    max_holding_bars=None,
):
    """Kısmi TP ve gecikmeli trailing-stop simülasyonu (journal ile aynı mum mantığı).

    TP ağırlıkları normalize edilir. trade_journal.resolve_signal_outcome ile
    birebir aynı mum değerlendirmesi kullanılır: hedefler sırayla dolu; her
    dolumdan sonra taşınan koruyucu stop bu mumun aralığındaysa kalan pozisyon
    AYNI MUMDA konservatif kapanır ve sonraki hedef sayılmaz (OHLC mum içi
    fiyat sırasını kanıtlayamaz → iyimser varsayım yok). İlk stopta gap varsa
    gerçekleşme fiyatı mum açılışıdır; taşınan stopta journal gibi stop
    fiyatı kullanılır.
    """
    direction = (direction or "LONG").upper()
    entry = _num(entry)
    stop = _num(stop_loss)
    tp1, tp2, tp3 = _tps(targets)
    levels = [(i, tp) for i, tp in enumerate([tp1, tp2, tp3], start=1) if tp is not None]
    if entry is None or stop is None or not future_candles or not levels:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    risk_distance = abs(entry - stop)
    if risk_distance == 0:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    n = len(levels)
    all_future_candles = list(future_candles)
    horizon = max(1, int(max_holding_bars)) if max_holding_bars is not None else None
    simulation_candles = all_future_candles[:horizon] if horizon is not None else all_future_candles
    if tp_weights and isinstance(tp_weights, dict):
        weights = []
        for level_no, _ in levels:
            try:
                weight = float(tp_weights.get(f"tp{level_no}", 1.0))
            except (TypeError, ValueError, OverflowError):
                weight = 0.0
            weights.append(weight if math.isfinite(weight) and weight > 0 else 0.0)
    else:
        weights = [1.0] * n
    total_w = sum(weights)
    if not math.isfinite(total_w) or total_w <= 0:
        weights = [1.0] * n
        total_w = float(n)
    weights = [w / total_w for w in weights]

    is_long = direction in ("LONG", "BUY")
    realized_rr = 0.0
    closed_frac = 0.0
    reached_tp = 0
    trailing_stop = stop
    exit_reason = None
    exit_offset = None
    exit_price = None
    exit_notional = 0.0
    stop_gap = False
    stop_gap_distance = 0.0
    stop_gap_r = 0.0

    weight_by_level = {
        level_no: weights[index] for index, (level_no, _) in enumerate(levels)
    }
    tp_by_level = dict(levels)
    hit_levels = set()
    reached_order = []

    for candle_offset, candle in enumerate(simulation_candles):
        low = _num(candle.low)
        high = _num(candle.high)
        opened = _num(getattr(candle, "open", None))
        if low is None or high is None:
            continue

        # Mum açılışı stopun ötesindeyse stop fiyatı değil açılış fiyatı kullanılır.
        if is_long:
            stop_gap = opened is not None and opened <= trailing_stop
            stop_touched = low <= trailing_stop
            stop_fill = opened if stop_gap else trailing_stop
        else:
            stop_gap = opened is not None and opened >= trailing_stop
            stop_touched = high >= trailing_stop
            stop_fill = opened if stop_gap else trailing_stop


        if stop_touched:
            remaining = 1.0 - closed_frac
            if remaining > 0.0:
                rr_stop = (
                    (stop_fill - entry) / risk_distance
                    if is_long
                    else (entry - stop_fill) / risk_distance
                )
                realized_rr += remaining * rr_stop
                closed_frac = 1.0
            exit_reason = "STOP" if reached_tp == 0 else "TRAILING_STOP"
            exit_offset = candle_offset
            exit_price = stop_fill
            exit_notional += remaining * stop_fill
            stop_gap = bool(stop_gap)
            stop_gap_distance = (
                max(0.0, trailing_stop - stop_fill) if is_long
                else max(0.0, stop_fill - trailing_stop)
            ) if stop_gap else 0.0
            stop_gap_r = stop_gap_distance / risk_distance
            break

        # trade_journal ile birebir mum mantığı: mum başındaki taşınan stop
        # saklanır, hedefler sırayla değerlendirilir; her dolumdan sonra yeni
        # stop bu mumun aralığındaysa kalan pozisyon AYNI MUMDA kapanır ve
        # sonraki hedefler sayılmaz (OHLC sıra kanıtı yok → konservatif).
        carried_stop = trailing_stop
        for level_no, tp_price in levels:
            if level_no in hit_levels:
                continue
            hit = high >= tp_price if is_long else low <= tp_price
            if not hit:
                continue

            weight = weight_by_level[level_no]
            rr = (
                (tp_price - entry) / risk_distance
                if is_long
                else (entry - tp_price) / risk_distance
            )
            realized_rr += weight * rr
            closed_frac += weight
            reached_tp = level_no
            exit_price = tp_price
            exit_notional += weight * tp_price
            hit_levels.add(level_no)
            reached_order.append(level_no)

            # Koruyucu stop taşıma: journal kuralı (ilk TP1 → breakeven,
            # TP2 sonrası → TP1 seviyesi; aksi halde stop korunur).
            if level_no == 1:
                if is_long:
                    trailing_stop = max(carried_stop if carried_stop is not None else stop, entry)
                else:
                    trailing_stop = min(carried_stop if carried_stop is not None else stop, entry)
            elif level_no == 2 and 3 not in hit_levels and 1 in tp_by_level:
                trailing_stop = tp_by_level[1]

            if closed_frac >= 1.0 - 1e-9:
                exit_reason = f"TP{reached_tp}"
                exit_offset = candle_offset
                break

            # Journalın aynı-mum konservatif kontrolü: taşınan stop bu mumun
            # aralığında ise kalan pay burada, stop fiyatından kapanır.
            remaining = 1.0 - closed_frac
            moved_stop_hit = remaining > 0.0 and (
                (is_long and low <= trailing_stop)
                or (not is_long and high >= trailing_stop)
            )
            if moved_stop_hit:
                rr_stop = (
                    (trailing_stop - entry) / risk_distance
                    if is_long
                    else (entry - trailing_stop) / risk_distance
                )
                realized_rr += remaining * rr_stop
                closed_frac = 1.0
                exit_reason = "TRAILING_STOP"
                exit_offset = candle_offset
                exit_price = trailing_stop
                exit_notional += remaining * trailing_stop
                stop_gap = False
                stop_gap_distance = 0.0
                stop_gap_r = 0.0
                break

        if closed_frac >= 1.0 - 1e-9:
            break

    if closed_frac < 1.0 - 1e-9:
        if horizon is None or len(simulation_candles) < horizon:
            return {"result": "OPEN", "tp": 0, "net_rr": 0.0}
        last_candle = simulation_candles[-1]
        last_close = _num(getattr(last_candle, "close", None))
        if last_close is None:
            return {"result": "OPEN", "tp": 0, "net_rr": 0.0}
        remaining = 1.0 - closed_frac
        time_exit_rr = ((last_close - entry) / risk_distance if is_long else (entry - last_close) / risk_distance)
        realized_rr += remaining * time_exit_rr
        exit_notional += remaining * last_close
        closed_frac = 1.0
        exit_price = last_close
        exit_offset = len(simulation_candles) - 1
        exit_reason = "TIME_EXIT"

    result = "WIN" if realized_rr > 0.0 else "LOSS"
    return {
        "result": result,
        "tp": reached_tp,
        "net_rr": _num(realized_rr, 4),
        "levels": list(reached_order),
        "exit_reason": exit_reason,
        "exit_offset": exit_offset,
        "exit_price": _num(exit_price),
        "average_exit": _num(exit_notional / max(closed_frac, 1e-12)),
        "stop_gap": stop_gap,
        "stop_gap_distance": _num(stop_gap_distance),
        "stop_gap_r": _num(stop_gap_r),
    }

def market_fallback_check(opened, planned_entry, stop, tp1, direction, risk=None,
                          legacy_fee_rate=None, maker_fee_rate=None,
                          taker_fee_rate=None, spread_rate=None, slippage_rate=None):
    """Shared gate for a missed LIMIT replaced by a nearby next-open MARKET."""
    is_long = str(direction or "").upper() == "LONG"
    if opened is None or planned_entry is None or stop is None or tp1 is None:
        return False, 0.0, "missing_levels"
    if (is_long and not (stop < opened < tp1)) or (not is_long and not (tp1 < opened < stop)):
        return False, 0.0, "invalid_geometry"
    distance = abs(opened - planned_entry)
    distance_pct = distance / opened if opened > 0 else float("inf")
    atr = _num((risk or {}).get("atr"))
    distance_atr = distance / atr if atr and atr > 0 else None
    max_pct = float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_PERCENT", 0.003))
    max_atr = float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_ATR", 0.35))
    if distance_pct > max_pct or (distance_atr is not None and distance_atr > max_atr):
        return False, 0.0, "distance"
    fallback_risk = abs(opened - stop)
    fallback_reward = tp1 - opened if is_long else opened - tp1
    if fallback_risk <= 0 or fallback_reward <= 0:
        return False, 0.0, "invalid_geometry"
    if legacy_fee_rate is not None:
        cost = abs(opened) * float(legacy_fee_rate)
    else:
        cost = estimate_plan_cost(
            entry_price=opened, targets={"tp1": tp1}, weights={"tp1": 1.0},
            entry_type="MARKET",
            maker_fee_rate=float(getattr(Config, "MAKER_FEE_RATE", 0.0002) if maker_fee_rate is None else maker_fee_rate),
            taker_fee_rate=float(getattr(Config, "TAKER_FEE_RATE", 0.00055) if taker_fee_rate is None else taker_fee_rate),
            spread_rate=float(getattr(Config, "STOP_SPREAD_BUFFER_RATE", 0.0002) if spread_rate is None else spread_rate),
            slippage_rate=float(getattr(Config, "STOP_SLIPPAGE_BUFFER_RATE", 0.0003) if slippage_rate is None else slippage_rate),
        )["total"]
    net_rr = (fallback_reward - cost) / fallback_risk
    minimum_net_rr = float(getattr(Config, "MINIMUM_NET_RR", 1.5))
    return net_rr >= minimum_net_rr, net_rr, "rr" if net_rr < minimum_net_rr else "ok"


def rebase_remaining_targets(risk, direction, candle, tp_weights=None,
                             maker_fee_rate=None, taker_fee_rate=None,
                             spread_rate=None, slippage_rate=None):
    """Shared stale-target rebase used before a resting LIMIT can fill."""
    direction = str(direction or "").upper()
    is_long = direction == "LONG"
    current_weights = risk.get("target_rebased_weights")
    if not isinstance(current_weights, dict):
        current_weights = tp_weights if isinstance(tp_weights, dict) else {}
    targets = [
        (index, _num(risk.get(f"tp{index}")), current_weights.get(f"tp{index}", 1.0))
        for index in range(1, 4)
        if _num(risk.get(f"tp{index}")) is not None
    ]
    if not targets:
        return False, "no_structural_targets"
    close = _num(getattr(candle, "close", None))
    high = _num(getattr(candle, "high", None))
    low = _num(getattr(candle, "low", None))
    entry = _num(risk.get("entry"))
    stop = _num(risk.get("stop_loss"))
    if None in (close, high, low, entry, stop):
        return False, "incomplete_levels"
    remaining = []
    for _, target, weight in targets:
        touched = high >= target if is_long else low <= target
        still_ahead = target > close if is_long else target < close
        if not touched and still_ahead:
            remaining.append((target, weight))
    if not remaining:
        return False, "no_remaining_structural_target"
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return False, "invalid_structural_risk"
    target_map = {f"tp{i}": item[0] for i, item in enumerate(remaining[:3], start=1)}
    rebased_weights = {f"tp{i}": item[1] for i, item in enumerate(remaining[:3], start=1)}
    cost = estimate_plan_cost(
        entry_price=entry, targets=target_map, weights=rebased_weights,
        entry_type="LIMIT",
        maker_fee_rate=float(getattr(Config, "MAKER_FEE_RATE", 0.0002) if maker_fee_rate is None else maker_fee_rate),
        taker_fee_rate=float(getattr(Config, "TAKER_FEE_RATE", 0.00055) if taker_fee_rate is None else taker_fee_rate),
        spread_rate=float(getattr(Config, "STOP_SPREAD_BUFFER_RATE", 0.0002) if spread_rate is None else spread_rate),
        slippage_rate=float(getattr(Config, "STOP_SLIPPAGE_BUFFER_RATE", 0.0003) if slippage_rate is None else slippage_rate),
    )
    first_target = remaining[0][0]
    first_reward = first_target - entry if is_long else entry - first_target
    net_first_rr = (first_reward - float(cost.get("total", 0.0))) / risk_distance
    minimum_net_rr = float(getattr(Config, "MINIMUM_NET_RR", 1.5))
    if first_reward <= 0 or net_first_rr < minimum_net_rr:
        return False, "remaining_target_net_rr_below_minimum"
    for index in range(1, 4):
        risk[f"tp{index}"] = remaining[index - 1][0] if index <= len(remaining) else None
    risk["target_rebased_weights"] = rebased_weights
    risk["target_rebased_after_pre_fill_touch"] = True
    risk["target_rebase_net_first_rr"] = round(net_first_rr, 4)
    return True, "remaining_structural_targets_rebased"


class BacktestRunner:
    """Fiyat serisini ileri sararak engine sinyallerini tetikler ve sonuç toplar."""

    def __init__(self, analyze_fn=None, fee_rate=None, partial_exits=True, tp_weights=None,
                 limit_expiry_bars=8, spread_rate=None, slippage_rate=None,
                 maker_fee_rate=None, taker_fee_rate=None, max_holding_bars=32):
        self.analyze_fn = analyze_fn
        # Explicit legacy fee_rate keeps older test/integration callers stable.
        # Production backtests pass maker/taker rates and use per-fill accounting.
        self.legacy_fee_rate = (
            self._safe_cost_rate(fee_rate)
            if fee_rate is not None and maker_fee_rate is None and taker_fee_rate is None
            else None
        )
        self.fee_rate = self.legacy_fee_rate if self.legacy_fee_rate is not None else 0.0
        self.maker_fee_rate = self._safe_cost_rate(
            getattr(Config, "MAKER_FEE_RATE", 0.0002) if maker_fee_rate is None else maker_fee_rate
        )
        self.taker_fee_rate = self._safe_cost_rate(
            getattr(Config, "TAKER_FEE_RATE", 0.00055) if taker_fee_rate is None else taker_fee_rate
        )
        legacy_mode = self.legacy_fee_rate is not None
        self.spread_rate = self._safe_cost_rate(
            (0.0 if legacy_mode else getattr(Config, "STOP_SPREAD_BUFFER_RATE", 0.0002))
            if spread_rate is None else spread_rate
        )
        self.slippage_rate = self._safe_cost_rate(
            (0.0 if legacy_mode else getattr(Config, "STOP_SLIPPAGE_BUFFER_RATE", 0.0003))
            if slippage_rate is None else slippage_rate
        )
        self.partial_exits = bool(partial_exits)
        self.tp_weights = tp_weights
        self.limit_expiry_bars = max(1, int(limit_expiry_bars))
        self.max_holding_bars = max(1, int(max_holding_bars))
        self.full_exit_calls = 0
        self.history = []
        self.total = 0
        self.wins = 0
        self.candidate_signals = 0
        self.unfilled_limits = 0
        self.expired_limits = 0
        self.stale_limits_cancelled = 0
        self.stale_limit_signal_candle_target = 0
        self.stale_limit_target_before_fill = 0
        self.stale_limit_targets_rebased = 0
        self.stale_limit_target_rebase_rejected = 0
        self.seen_setup_ids = set()
        self.duplicate_setups_skipped = 0
        self.market_fallback_fills = 0
        self.market_fallback_rejected_rr = 0
        self.market_fallback_rejected_distance = 0
        self.candidate_direction_counts = {}
        self.filled_direction_counts = {}
        self.unfilled_limit_direction_counts = {}
        self.expired_limit_direction_counts = {}
        self.stale_limit_direction_counts = {}
        self.overlapping_signals_skipped = 0
        self.open_trades = 0
        self.invalid_candidates = 0
        self.no_followup_data = 0
        self.tp1 = 0
        self.tp2 = 0
        self.tp3 = 0
        self.net_rr = 0.0
        self.funding_cost_r = 0.0
        self.funding_events_charged = 0
        self.funding_data_quality = {}
        self.microstructure_samples = 0
        self.microstructure_snapshots = 0
        self.microstructure_orderbooks = 0
        self.microstructure_trade_snapshots = 0
        # Diagnostic counters explain why historical analysis produces no trades.
        self.analysis_calls = 0
        # Strategy-level diagnostics are observational only; they never affect selection.
        self.strategy_observations = {}
        self.empty_results = 0
        self.raw_long_signals = 0
        self.raw_short_signals = 0
        self.non_directional_results = 0
        self.action_counts = {}
        self.wait_reason_counts = {}
        self.signal_reason_counts = {}
        self.mtf_alignment_counts = {}
        self.entry_reason_counts = {}
        self.entry_type_counts = {}
        self.risk_reason_counts = {}
        self.target_reason_counts = {}
        self.target_missing_rr_counts = {}
        self.stop_atr_buckets = {}
        self.mtf_entry_source_counts = {}
        self.liquidity_sweep_state_counts = {}
        self.confirmation_reason_counts = {}
        self.confirmation_outcome_counts = {}
        self.confirmation_requirement_counts = {}
        self.entry_type_reason_counts = {}
        self.entry_validity_counts = {}
        self.decision_blocker_counts = {}
        self.direction_action_counts = {}
        self.direction_blocker_counts = {}

    @staticmethod
    def _safe_cost_rate(value):
        try:
            rate = float(value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return rate if math.isfinite(rate) and rate > 0 else 0.0

    def reset(self):
        self.__init__(
            analyze_fn=self.analyze_fn,
            fee_rate=self.legacy_fee_rate,
            partial_exits=self.partial_exits,
            tp_weights=self.tp_weights,
            limit_expiry_bars=self.limit_expiry_bars,
            spread_rate=self.spread_rate,
            slippage_rate=self.slippage_rate,
            maker_fee_rate=None if self.legacy_fee_rate is not None else self.maker_fee_rate,
            taker_fee_rate=None if self.legacy_fee_rate is not None else self.taker_fee_rate,
        )

    def _record_strategy_diagnostics(self, result):
        """Accumulate the live seven-strategy report without changing its decision."""
        if not isinstance(result, dict):
            return
        report = result.get("strategy_lab")
        if not isinstance(report, dict):
            report = ((result.get("analysis") or {}).get("strategy_lab") or {})
        if not isinstance(report, dict):
            return
        diagnostics = report.get("diagnostics") or {}
        for row in diagnostics.get("strategies") or []:
            if not isinstance(row, dict):
                continue
            strategy_id = str(row.get("strategy_id") or "UNKNOWN")
            item = self.strategy_observations.setdefault(strategy_id, {
                "evaluations": 0, "raw_setups": 0, "common_filter_passed": 0,
                "selected": 0, "common_filter_rejected": 0, "no_setup": 0,
            })
            item["evaluations"] += 1
            status = str(row.get("status") or "").upper()
            stage = str(row.get("rejection_stage") or "").upper()
            if row.get("direction") in {"LONG", "SHORT"}:
                item["raw_setups"] += 1
            if status in {"FILTERED_SETUP", "FILTERED_NOT_SELECTED", "SELECTED"}:
                item["common_filter_passed"] += 1
            if status == "SELECTED" or row.get("selected") is True:
                item["selected"] += 1
            if stage == "COMMON_FILTER":
                item["common_filter_rejected"] += 1
            if not row.get("direction") and status not in {"BLOCKED_COMMON_FILTER"}:
                item["no_setup"] += 1

    def strategy_performance_breakdown(self):
        """Per-strategy generation, common-filter, selection and realized trade metrics."""
        output = {}
        for strategy_id, observations in self.strategy_observations.items():
            trades = [trade for trade in self.history
                      if str(trade.get("strategy_id") or "UNKNOWN") == strategy_id]
            output[strategy_id] = {
                **dict(observations),
                "filled_trades": len(trades),
                **self._trade_metrics(trades),
            }
        # Preserve visibility for selected/traded strategies even if no diagnostics were emitted.
        for trade in self.history:
            strategy_id = str(trade.get("strategy_id") or "UNKNOWN")
            if strategy_id not in output:
                trades = [item for item in self.history
                          if str(item.get("strategy_id") or "UNKNOWN") == strategy_id]
                output[strategy_id] = {
                    "evaluations": 0, "raw_setups": 0, "common_filter_passed": 0,
                    "selected": 0, "common_filter_rejected": 0, "no_setup": 0,
                    "filled_trades": len(trades), **self._trade_metrics(trades),
                }
        return output

    def run(self, data, on_signal=None, step=1, lenient=False):
        """data: {'15m': [Candle,...], '1h': [...], ...} -> her mum sonrası analiz + simülasyon.

        lenient=True ise decision kapısı atlanır; sinyal yönü LONG/SHORT ve entry geçerliyse
        işlem üretilir (ham sinyalin edge'i ölçülür).
        """
        self.funding_data_quality = data.get("derivatives_data_quality") or {
            "funding": "HISTORICAL" if data.get("funding_records") else "NOT_PROVIDED"
        }
        candles = data.get("15m") or data.get("15M")
        if not candles:
            return self.statistics()

        total = len(candles)
        warmup = 300
        busy_until_index = -1
        for idx in range(warmup, total, max(1, step)):
            # Signal decision is made at the close of the current 15m candle.
            decision_time_ms = candles[idx].time + 15 * 60 * 1000
            window = {
                tf: candles[: idx + 1] if tf == "15m" else _window_up_to(data.get(tf), decision_time_ms, tf)
                for tf in ("15m", "1h", "4h", "1d", "1w")
            }
            window["symbol"] = data.get("symbol", "SYMBOL")
            # Preserve comparison universes and only pre-decision derivatives/L2 data.
            if data.get("smt_universe"):
                window["smt_universe"] = data["smt_universe"]
            window["funding_records"] = [
                item for item in (data.get("funding_records") or [])
                if int(item.get("timestamp") or 0) <= decision_time_ms
            ]
            oi_records = [
                item for item in (data.get("open_interest_records") or [])
                if int(item.get("timestamp") or 0) <= decision_time_ms
            ]
            window["open_interest"] = [item["value"] for item in oi_records]
            window["open_interest_timestamps_ms"] = [item["timestamp"] for item in oi_records]
            window["funding_rate"] = [item["value"] for item in window["funding_records"]]
            window["funding_rate_timestamps_ms"] = [item["timestamp"] for item in window["funding_records"]]
            window["derivatives_data_quality"] = data.get("derivatives_data_quality", {})
            try:
                from microstructure_archive import snapshot_at
                micro = snapshot_at(window["symbol"], decision_time_ms) or {}
            except Exception:
                micro = {}
            self.microstructure_samples += 1
            if micro.get("microstructure_snapshot_timestamp_ms"):
                self.microstructure_snapshots += 1
            if isinstance(micro.get("orderbook"), dict):
                self.microstructure_orderbooks += 1
            if isinstance(micro.get("recent_trades"), list) and micro.get("recent_trades"):
                self.microstructure_trade_snapshots += 1
            window.update(micro)

            self.analysis_calls += 1
            result = self.analyze_fn(window) if self.analyze_fn else on_signal(window)

            if not result:
                self.empty_results += 1
                continue
            self._record_strategy_diagnostics(result)
            signal = (result.get("signal") or {}) if isinstance(result, dict) else {}
            decision = (result.get("decision") or {}) if isinstance(result, dict) else {}
            signal_dir = str(signal.get("signal", "")).upper()
            action = str(decision.get("action", "MISSING")).upper() or "MISSING"
            self.action_counts[action] = self.action_counts.get(action, 0) + 1
            if signal_dir in {"LONG", "SHORT"}:
                direction_action = f"{signal_dir}|{action}"
                self.direction_action_counts[direction_action] = self.direction_action_counts.get(direction_action, 0) + 1
            if signal_dir not in {"LONG", "SHORT"}:
                wait_reason = str(signal.get("wait_reason") or "unspecified")
                self.wait_reason_counts[wait_reason] = self.wait_reason_counts.get(wait_reason, 0) + 1
            signal_reason = str(signal.get("signal_reason") or "unspecified")
            self.signal_reason_counts[signal_reason] = self.signal_reason_counts.get(signal_reason, 0) + 1
            analysis = result.get("analysis") if isinstance(result, dict) else {}
            mtf = (analysis or {}).get("mtf") if isinstance(analysis, dict) else {}
            if isinstance(mtf, dict):
                alignment = "|".join(
                    f"{key}={str(mtf.get(key, 'UNKNOWN')).upper()}"
                    for key in ("entry", "weekly", "daily", "h4")
                )
                self.mtf_alignment_counts[alignment] = self.mtf_alignment_counts.get(alignment, 0) + 1
            if isinstance(mtf, dict):
                source = str(mtf.get("entry_source") or "UNKNOWN").upper()
                self.mtf_entry_source_counts[source] = self.mtf_entry_source_counts.get(source, 0) + 1
            sweep_meta = (analysis or {}).get("liquidity_sweep") if isinstance(analysis, dict) else {}
            if isinstance(sweep_meta, dict):
                post = sweep_meta.get("post_structure") or {}
                sweep_key = (
                    f"sweep={bool(sweep_meta.get('is_sweep'))}|"
                    f"confirmed={bool(post.get('confirmed'))}|"
                    f"side={str(sweep_meta.get('sweep_side') or 'NONE').upper()}"
                )
                self.liquidity_sweep_state_counts[sweep_key] = self.liquidity_sweep_state_counts.get(sweep_key, 0) + 1
            entry_meta = (analysis or {}).get("entry") if isinstance(analysis, dict) else {}
            confirmation_meta = (analysis or {}).get("confirmation") if isinstance(analysis, dict) else {}
            if isinstance(confirmation_meta, dict):
                confirmed = bool(confirmation_meta.get("confirmed"))
                outcome = "CONFIRMED" if confirmed else "NOT_CONFIRMED"
                self.confirmation_outcome_counts[outcome] = self.confirmation_outcome_counts.get(outcome, 0) + 1
                reason = str(confirmation_meta.get("reason") or "unspecified")
                self.confirmation_reason_counts[reason] = self.confirmation_reason_counts.get(reason, 0) + 1

                # The optimizer stores its profile on the entry payload. Read
                # that source first; confirmation also mirrors it for consumers.
                profile = (
                    confirmation_meta.get("confirmation_profile")
                    or (entry_meta.get("confirmation_profile") if isinstance(entry_meta, dict) else None)
                    or {}
                )
                profile_mode = str(profile.get("mode") or "UNAVAILABLE").upper() if isinstance(profile, dict) else "UNAVAILABLE"
                requirements = (
                    confirmation_meta.get("requirements")
                    or confirmation_meta.get("confirmation_requirements")
                    or (entry_meta.get("confirmation_requirements") if isinstance(entry_meta, dict) else None)
                    or {}
                )
                if isinstance(requirements, dict) and requirements.get("require_choch_or_reclaim"):
                    label = "CHOCH_OR_RECLAIM"
                elif profile_mode == "DIRECTIONAL_BREAK":
                    label = "DIRECTIONAL_BREAK"
                else:
                    label = profile_mode
                self.confirmation_requirement_counts[label] = self.confirmation_requirement_counts.get(label, 0) + 1
            if isinstance(entry_meta, dict):
                entry_reason = str(entry_meta.get("entry_reason_code") or entry_meta.get("reason") or "unspecified")
                self.entry_reason_counts[entry_reason] = self.entry_reason_counts.get(entry_reason, 0) + 1
                entry_type = str(entry_meta.get("entry_type") or "NONE").upper()
                type_reason = str(entry_meta.get("entry_type_reason") or "unspecified")
                self.entry_type_reason_counts[type_reason] = self.entry_type_reason_counts.get(type_reason, 0) + 1
                validity = "VALID" if entry_meta.get("valid") else "INVALID"
                self.entry_validity_counts[validity] = self.entry_validity_counts.get(validity, 0) + 1
                self.entry_type_counts[entry_type] = self.entry_type_counts.get(entry_type, 0) + 1
            blockers = decision.get("critical_blockers") or decision.get("blockers") or []
            if isinstance(blockers, str):
                blockers = [blockers]
            if isinstance(blockers, (list, tuple)):
                for blocker in blockers:
                    key = str(blocker).strip()
                    if key:
                        self.decision_blocker_counts[key] = self.decision_blocker_counts.get(key, 0) + 1
                        if signal_dir in {"LONG", "SHORT"}:
                            side_key = f"{signal_dir}|{key}"
                            self.direction_blocker_counts[side_key] = self.direction_blocker_counts.get(side_key, 0) + 1
            risk_meta = result.get("risk") if isinstance(result, dict) else {}
            if isinstance(risk_meta, dict) and risk_meta.get("risk_setup_valid") is False:
                risk_reason = str(risk_meta.get("reason_code") or risk_meta.get("risk_setup_reason") or "unspecified")
                self.risk_reason_counts[risk_reason] = self.risk_reason_counts.get(risk_reason, 0) + 1
            if isinstance(risk_meta, dict):
                atr_value = _num(risk_meta.get("atr"))
                # Report the final executable stop, not the pre-expansion request.
                stop_distance = _num(risk_meta.get("risk"))
                if stop_distance is None:
                    stop_distance = _num(risk_meta.get("requested_risk"))
                if atr_value and atr_value > 0 and stop_distance is not None:
                    ratio = stop_distance / atr_value
                    bucket = "<0.10 ATR" if ratio < 0.10 else "<0.25 ATR" if ratio < 0.25 else "<0.50 ATR" if ratio < 0.50 else ">=0.50 ATR"
                    self.stop_atr_buckets[bucket] = self.stop_atr_buckets.get(bucket, 0) + 1
            target_meta = (analysis or {}).get("dynamic_tp") if isinstance(analysis, dict) else {}
            if isinstance(target_meta, dict):
                target_reason = str(target_meta.get("reason") or "unspecified")
                self.target_reason_counts[target_reason] = self.target_reason_counts.get(target_reason, 0) + 1
                missing_rr = target_meta.get("missing_rr_level")
                if missing_rr is not None:
                    label = f"{float(missing_rr):g}R"
                    self.target_missing_rr_counts[label] = self.target_missing_rr_counts.get(label, 0) + 1
            if signal_dir == "LONG":
                self.raw_long_signals += 1
            elif signal_dir == "SHORT":
                self.raw_short_signals += 1
            else:
                self.non_directional_results += 1
            # One symbol can have only one active position or pending LIMIT
            # at a time. Keep analyzing candles for diagnostics, but do not
            # count overlapping entries as independent portfolio trades.
            if idx <= busy_until_index:
                decision = result.get("decision") if isinstance(result, dict) else {}
                if isinstance(decision, dict) and str(decision.get("action", "")).upper() == "EXECUTE":
                    self.overlapping_signals_skipped += 1
                continue

            setup_identity = self._setup_identity(result)
            if setup_identity is not None and setup_identity in self.seen_setup_ids:
                self.duplicate_setups_skipped += 1
                continue

            open_before = self.open_trades
            unfilled_before = self.unfilled_limits
            candidates_before = self.candidate_signals
            trade = self._to_trade(result, candles, idx + 1, lenient=lenient, signal_index=idx, funding_records=data.get("funding_records"))
            if self.candidate_signals > candidates_before and setup_identity is not None:
                self.seen_setup_ids.add(setup_identity)
            if trade is not None:
                self._record(trade)
                exit_index = trade.get("exit_index")
                if exit_index is not None:
                    busy_until_index = max(busy_until_index, int(exit_index))
            elif self.open_trades > open_before:
                # An unresolved trade remains open through the end of this
                # historical window; no second position may overlap it.
                busy_until_index = total - 1
            elif self.unfilled_limits > unfilled_before:
                # The pending order occupied this symbol until its expiry.
                busy_until_index = min(total - 1, idx + self.limit_expiry_bars - 1)

        return self.statistics()

    def _setup_identity(self, result):
        """Stable identity for one structural POI; ignores candle-to-candle entry drift."""
        payload = result if isinstance(result, dict) else {}
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        entry = analysis.get("entry") if isinstance(analysis.get("entry"), dict) else {}
        risk = payload.get("risk") if isinstance(payload.get("risk"), dict) else {}
        signal = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
        direction = str(signal.get("signal") or entry.get("direction") or "").upper()
        if direction not in {"LONG", "SHORT"}:
            return None
        zone = entry.get("poi_zone") if isinstance(entry.get("poi_zone"), dict) else {}
        low = _num(zone.get("low"), digits=8)
        high = _num(zone.get("high"), digits=8)
        candidate_id = str(entry.get("setup_candidate_id") or "").strip()
        source = str(entry.get("poi_source") or "").upper()
        stop = _num(risk.get("stop_loss"), digits=8)
        if candidate_id and low is not None and high is not None:
            return (direction, candidate_id, source, low, high)
        if low is not None and high is not None:
            return (direction, source, low, high, stop)
        # Without a stable POI identity there is no safe basis for deduplication.
        # Do not collapse unrelated MARKET signals that happen to share levels.
        return None

    def _rebase_remaining_targets(self, risk, direction, candle):
        return rebase_remaining_targets(
            risk, direction, candle, tp_weights=self.tp_weights,
            maker_fee_rate=self.maker_fee_rate, taker_fee_rate=self.taker_fee_rate,
            spread_rate=self.spread_rate, slippage_rate=self.slippage_rate,
        )

    def _market_fallback_check(self, opened, planned_entry, stop, tp1, direction, risk):
        return market_fallback_check(
            opened, planned_entry, stop, tp1, direction, risk,
            legacy_fee_rate=self.legacy_fee_rate,
            maker_fee_rate=self.maker_fee_rate,
            taker_fee_rate=self.taker_fee_rate,
            spread_rate=self.spread_rate,
            slippage_rate=self.slippage_rate,
        )

    def _to_trade(self, result, candles, entry_index, lenient=False, signal_index=None, funding_records=None):
        """analyze çıktısından trade üretir; geçersizse None."""
        decision = (result or {}).get("decision") or {}
        signal = (result or {}).get("signal") or {}
        action = str(decision.get("action", "")).upper()
        signal_dir = str(signal.get("signal", "")).upper()

        if lenient:
            tradeable_dir = signal_dir in ("LONG", "SHORT")
        else:
            tradeable_dir = signal_dir in ("LONG", "SHORT") and action in ("EXECUTE", "EXECUTE_WITH_CAUTION")
        if not tradeable_dir:
            return None
        if not lenient and (
            decision.get("entry_valid") is False
            or decision.get("risk_valid") is False
        ):
            self.invalid_candidates += 1
            return None
        self.candidate_signals += 1
        self.candidate_direction_counts[signal_dir] = self.candidate_direction_counts.get(signal_dir, 0) + 1

        risk = dict((result or {}).get("risk") or {})
        risk_side = str(risk.get("side") or "").upper()
        if risk_side in {"LONG", "SHORT"} and risk_side != signal_dir:
            self.invalid_candidates += 1
            return None
        if isinstance(risk, dict) and risk.get("risk_setup_valid") is False:
            self.invalid_candidates += 1
            return None

        planned_entry = risk.get("entry")
        stop = risk.get("stop_loss")
        if entry_index >= len(candles):
            self.no_followup_data += 1
            return None
        if planned_entry is None or stop is None:
            self.invalid_candidates += 1
            return None

        analysis = (result or {}).get("analysis") or {}
        entry_meta = analysis.get("entry") or {}
        entry_type = str(entry_meta.get("entry_type") or "MARKET").upper()
        if entry_type not in {"MARKET", "LIMIT"}:
            self.invalid_candidates += 1
            return None

        # Simulate the order type Atlas actually recommends. A LIMIT order is
        # not filled merely because a signal exists; price must trade at its
        # level. MARKET orders fill at the next candle open, not the old signal
        # candle close.
        fill_index = None
        entry_price = None
        limit_intrabar_fill = False
        market_fallback_used = False
        if entry_type == "MARKET":
            fill_index = entry_index
            entry_price = _num(candles[fill_index].open)
            if entry_price is None:
                self.invalid_candidates += 1
                return None
        else:
            limit_price = _num(planned_entry)
            if limit_price is None:
                self.invalid_candidates += 1
                return None
            is_long = signal_dir == "LONG"

            # A target touched on the signal candle is removed from the plan.
            # The pending LIMIT may continue only if a later structural target
            # remains ahead of price and still pays for its execution costs.
            if signal_index is not None and 0 <= signal_index < entry_index and signal_index < len(candles):
                signal_candle = candles[signal_index]
                target_hit_before_order = any(
                    (signal_candle.high >= target if is_long else signal_candle.low <= target)
                    for target in (_num(risk.get("tp1")), _num(risk.get("tp2")), _num(risk.get("tp3")))
                    if target is not None
                )
                if target_hit_before_order:
                    # Count the stale target event independently of whether
                    # the remaining plan can be rebased or must be cancelled.
                    self.stale_limit_signal_candle_target += 1
                    rebased, _ = self._rebase_remaining_targets(risk, signal_dir, signal_candle)
                    if rebased:
                        self.stale_limit_targets_rebased += 1
                    else:
                        self.stale_limits_cancelled += 1
                        self.stale_limit_direction_counts[signal_dir] = self.stale_limit_direction_counts.get(signal_dir, 0) + 1
                        return None

            expiry_index = min(len(candles), entry_index + self.limit_expiry_bars)
            for candidate_index in range(entry_index, expiry_index):
                candle = candles[candidate_index]
                opened = _num(candle.open)
                if opened is None:
                    continue
                gap_fill = (opened <= limit_price) if is_long else (opened >= limit_price)
                touched = candle.low <= limit_price if is_long else candle.high >= limit_price
                # Assess a next-open MARKET replacement before using the full
                # candle range: the open is known before any later target touch.
                if not touched:
                    fallback_ok, fallback_net_rr, fallback_reason = self._market_fallback_check(
                        opened, limit_price, _num(stop), _num(risk.get("tp1")), signal_dir, risk
                    )
                    if fallback_ok:
                        entry_price = opened
                        fill_index = candidate_index
                        entry_type = "MARKET_FALLBACK"
                        limit_intrabar_fill = False
                        market_fallback_used = True
                        break
                    if fallback_reason == "distance":
                        self.market_fallback_rejected_distance += 1
                    elif fallback_reason == "rr":
                        self.market_fallback_rejected_rr += 1

                target_already_hit = any(
                    (candle.high >= target if is_long else candle.low <= target)
                    for target in (_num(risk.get("tp1")), _num(risk.get("tp2")), _num(risk.get("tp3")))
                    if target is not None
                )
                if target_already_hit and not touched:
                    # Count target contact before fill even when the remaining
                    # targets are valid and the LIMIT is allowed to stay active.
                    self.stale_limit_target_before_fill += 1
                    # If the LIMIT remains pending after the candle, remove
                    # targets already traded through and keep viable targets ahead.
                    rebased, _ = self._rebase_remaining_targets(risk, signal_dir, candle)
                    if rebased:
                        self.stale_limit_targets_rebased += 1
                    else:
                        self.stale_limit_target_rebase_rejected += 1
                        self.stale_limits_cancelled += 1
                        self.stale_limit_direction_counts[signal_dir] = self.stale_limit_direction_counts.get(signal_dir, 0) + 1
                        return None
                # If entry and target are touched in one candle, event order is unknown.
                if not touched:
                    continue
                entry_price = min(limit_price, opened) if is_long else max(limit_price, opened)
                if gap_fill:
                    # A marketable resting LIMIT takes liquidity at the open;
                    # charge taker fee and market friction, not maker pricing.
                    entry_type = "MARKETABLE_LIMIT"
                # If price opens through the limit, fill is at the open and
                # the candle's later range can be simulated. Otherwise the
                # intrabar path is unknown: do not count a TP touched before
                # the limit fill as a win.
                limit_intrabar_fill = not (
                    (is_long and opened <= limit_price)
                    or (not is_long and opened >= limit_price)
                )
                fill_index = candidate_index
                break
            if fill_index is None:
                if len(candles) < entry_index + self.limit_expiry_bars:
                    self.no_followup_data += 1
                else:
                    self.expired_limits += 1
                    self.expired_limit_direction_counts[signal_dir] = self.expired_limit_direction_counts.get(signal_dir, 0) + 1
                self.unfilled_limits += 1
                self.unfilled_limit_direction_counts[signal_dir] = self.unfilled_limit_direction_counts.get(signal_dir, 0) + 1
                return None

        stop = _num(stop)
        if stop is None:
            self.invalid_candidates += 1
            return None
        tps = [_num(risk.get("tp1")), _num(risk.get("tp2")), _num(risk.get("tp3"))]
        valid_tps = [target for target in tps if target is not None]
        if signal_dir == "LONG":
            if stop >= entry_price or any(target <= entry_price for target in valid_tps):
                self.invalid_candidates += 1
                return None
            if valid_tps != sorted(valid_tps):
                self.invalid_candidates += 1
                return None
        else:
            if stop <= entry_price or any(target >= entry_price for target in valid_tps):
                self.invalid_candidates += 1
                return None
            if valid_tps != sorted(valid_tps, reverse=True):
                self.invalid_candidates += 1
                return None

        if market_fallback_used:
            self.market_fallback_fills += 1
        self.filled_direction_counts[signal_dir] = self.filled_direction_counts.get(signal_dir, 0) + 1

        use_partial = bool(getattr(self, "partial_exits", True))
        trade_tp_weights = risk.get("target_rebased_weights") or self.tp_weights
        if limit_intrabar_fill:
            fill_candle = candles[fill_index]
            fill_stop_hit = _candle_touched_stop(
                signal_dir == "LONG", stop, fill_candle.low, fill_candle.high
            )
            if fill_stop_hit:
                fill_target_hit = any(
                    (fill_candle.high >= target if signal_dir == "LONG" else fill_candle.low <= target)
                    for target in tps if target is not None
                )
                outcome = {"result": "LOSS", "tp": 0, "net_rr": -1.0, "levels": [],
                           "exit_reason": "STOP_AND_TARGET_SAME_BAR_STOP_FIRST" if fill_target_hit else "STOP", "exit_offset": 0,
                           "exit_price": stop, "stop_gap": False,
                           "stop_gap_distance": 0.0, "stop_gap_r": 0.0}
                outcome_start_index = fill_index
            else:
                # Exclude the fill candle from target simulation. Its high/low
                # may have occurred before the intrabar limit order was filled.
                future = candles[fill_index + 1:fill_index + self.max_holding_bars]
                outcome_start_index = fill_index + 1
                horizon_after_fill = max(1, self.max_holding_bars - 1)
                if use_partial:
                    outcome = simulate_trade_partial(
                        entry=entry_price, stop_loss=stop, targets=tps,
                        future_candles=future, direction=signal_dir,
                        tp_weights=trade_tp_weights, max_holding_bars=horizon_after_fill,
                    )
                else:
                    outcome = simulate_trade(
                        entry=entry_price, stop_loss=stop, targets=tps,
                        future_candles=future, direction=signal_dir,
                        round_trip_cost_rate=self.fee_rate, max_holding_bars=horizon_after_fill,
                    )
        else:
            # MARKET and gap-through LIMIT orders fill at candle open.
            future = candles[fill_index:fill_index + self.max_holding_bars]
            outcome_start_index = fill_index
            if use_partial:
                outcome = simulate_trade_partial(
                    entry=entry_price, stop_loss=stop, targets=tps,
                    future_candles=future, direction=signal_dir,
                    tp_weights=trade_tp_weights, max_holding_bars=self.max_holding_bars,
                )
            else:
                outcome = simulate_trade(
                    entry=entry_price, stop_loss=stop, targets=tps,
                    future_candles=future, direction=signal_dir,
                    round_trip_cost_rate=self.fee_rate, max_holding_bars=self.max_holding_bars,
                )

        # Pencere içinde çözülemeyen (ne SL ne TP) işlemleri istatistiğe katma.
        if outcome.get("result") == "OPEN":
            self.open_trades += 1
            return None

        risk_distance = abs(entry_price - stop)
        # One shared fill-level cost model keeps backtest costs consistent with
        # RiskEngine. OHLCV cannot reveal queue position or exact market impact.
        gross_rr = float(outcome.get("net_rr", 0.0) or 0.0)
        if self.legacy_fee_rate is not None:
            fee_cost = abs(entry_price) * self.legacy_fee_rate
            spread_cost = abs(entry_price) * self.spread_rate
            slippage_cost = abs(entry_price) * self.slippage_rate
            fee_rr = fee_cost / risk_distance if risk_distance > 0 else 0.0
            spread_slippage_rr = (spread_cost + slippage_cost) / risk_distance if risk_distance > 0 else 0.0
            execution_cost_rr = fee_rr + spread_slippage_rr
            cost_parts = {"entry_fee": fee_cost, "exit_fee": 0.0, "spread": spread_cost, "slippage": slippage_cost}
        else:
            cost_parts = realized_trade_cost(
                entry_price=entry_price,
                exit_price=_num(outcome.get("exit_price")) or entry_price,
                entry_type=entry_type,
                exit_reason=outcome.get("exit_reason"),
                targets=tps,
                reached_levels=outcome.get("levels") or ([outcome.get("tp")] if outcome.get("tp") else []),
                tp_weights=trade_tp_weights,
                partial_exits=use_partial,
                maker_fee_rate=self.maker_fee_rate,
                taker_fee_rate=self.taker_fee_rate,
                spread_rate=self.spread_rate,
                slippage_rate=self.slippage_rate,
            )
            execution_cost_rr = cost_parts["total"] / risk_distance if risk_distance > 0 else 0.0
            fee_rr = (cost_parts["entry_fee"] + cost_parts["exit_fee"]) / risk_distance if risk_distance > 0 else 0.0
            spread_slippage_rr = (cost_parts["spread"] + cost_parts["slippage"]) / risk_distance if risk_distance > 0 else 0.0
        # Preserve actual price-path R (including stop gaps) and subtract costs once.
        signal_index = max(0, int(signal_index if signal_index is not None else entry_index - 1))
        exit_offset = outcome.get("exit_offset")
        exit_index = (outcome_start_index + int(exit_offset)
                      if exit_offset is not None else None)
        exit_time = int(candles[exit_index].time) if exit_index is not None and exit_index < len(candles) else None
        funding_result = adverse_funding_cost_r(
            signal_dir, entry_price, risk_distance,
            int(candles[fill_index].time),
            int(candles[exit_index].time) + 15 * 60 * 1000 if exit_index is not None and exit_index < len(candles) else int(candles[fill_index].time),
            candles=candles[fill_index:exit_index + 1] if exit_index is not None and exit_index < len(candles) else [candles[fill_index]],
            funding_records=funding_records or (), timeframe_ms=15 * 60 * 1000,
        )
        funding_pnl_r = funding_result["funding_pnl_r"]
        funding_cost_r = funding_result["funding_cost_r"]
        net_rr = round(gross_rr - execution_cost_rr - funding_cost_r, 4)
        entry_fee_rr = cost_parts.get("entry_fee", 0.0) / risk_distance if risk_distance > 0 else 0.0
        exit_fee_rr = cost_parts.get("exit_fee", 0.0) / risk_distance if risk_distance > 0 else 0.0
        spread_rr = cost_parts.get("spread", 0.0) / risk_distance if risk_distance > 0 else 0.0
        slippage_rr = cost_parts.get("slippage", 0.0) / risk_distance if risk_distance > 0 else 0.0
        cost_reconciliation_error_rr = (gross_rr - execution_cost_rr - funding_cost_r) - net_rr
        strategy_report = (result or {}).get("strategy_lab") or analysis.get("strategy_lab") or {}
        selected_strategy_id = (
            strategy_report.get("diagnostics", {}).get("selected_strategy_id")
            or ((strategy_report.get("selected") or {}).get("strategy_id"))
            or decision.get("selected_strategy_id")
            or signal.get("strategy_id")
            or "UNKNOWN"
        )
        return {
            "strategy_id": str(selected_strategy_id),
            "signal_index": signal_index,
            "signal_time": int(candles[signal_index].time),
            "entry_index": fill_index,
            "entry_time": int(candles[fill_index].time),
            "fill_delay_bars": max(0, fill_index - entry_index),
            "entry_type": entry_type,
            "market_phase": (
                (analysis.get("market_phase") or {}).get("phase")
                if isinstance(analysis.get("market_phase"), dict)
                else analysis.get("market_phase") or "UNKNOWN"
            ),
            "market_regime": (
                (analysis.get("market_regime") or {}).get("regime")
                if isinstance(analysis.get("market_regime"), dict)
                else analysis.get("market_regime") or "UNKNOWN"
            ),
            "volatility": (
                "HIGH" if _num((analysis.get("market_regime") or {}).get("volatility_ratio")) is not None
                and _num((analysis.get("market_regime") or {}).get("volatility_ratio")) >= 1.65
                else "LOW" if _num((analysis.get("market_regime") or {}).get("volatility_ratio")) is not None
                and _num((analysis.get("market_regime") or {}).get("volatility_ratio")) <= 0.72
                else "NORMAL" if _num((analysis.get("market_regime") or {}).get("volatility_ratio")) is not None
                else "UNKNOWN"
            ),
            "poi_type": (
                (analysis.get("entry") or {}).get("poi_type")
                or (analysis.get("entry") or {}).get("poi_source")
                or (analysis.get("entry") or {}).get("source")
                or analysis.get("entry_source")
                or "UNKNOWN"
            ) if isinstance(analysis.get("entry") or {}, dict) else "UNKNOWN",
            "planned_entry": _num(planned_entry),
            "direction": signal_dir,
            "entry": entry_price,
            "stop_loss": stop,
            "initial_risk_distance": _num(risk_distance),
            "tps": tps,
            "exit_price": _num(outcome.get("exit_price")),
            "stop_gap": bool(outcome.get("stop_gap", False)),
            "stop_gap_distance": _num(outcome.get("stop_gap_distance", 0.0)),
            "stop_gap_r": _num(outcome.get("stop_gap_r", 0.0)),
            "mtf_context": {
                key: (analysis.get("mtf") or {}).get(key)
                for key in ("entry", "weekly", "daily", "h4", "entry_source")
            } if isinstance(analysis.get("mtf"), dict) else {},
            "exit_reason": outcome.get("exit_reason", "UNKNOWN"),
            "exit_index": exit_index,
            "exit_time": exit_time,
            "result": outcome.get("result"),
            "tp": outcome.get("tp", 0),
            # Keep price-path performance separate from modeled execution costs.
            # A normal stop is approximately -1 gross R; net R can be lower
            # when fees/spread/slippage are large relative to the stop distance.
            "gross_rr": round(gross_rr, 4),
            "net_rr": round(max(net_rr, -99.0), 4),
            "fee_rr": round(fee_rr, 4),
            "entry_fee_rr": round(entry_fee_rr, 4),
            "exit_fee_rr": round(exit_fee_rr, 4),
            "spread_rr": round(spread_rr, 4),
            "slippage_rr": round(slippage_rr, 4),
            "spread_slippage_rr": round(spread_slippage_rr, 4),
            "cost_reconciliation_error_rr": round(cost_reconciliation_error_rr, 8),
            "entry_fee_quote": round(cost_parts.get("entry_fee", 0.0), 10),
            "exit_fee_quote": round(cost_parts.get("exit_fee", 0.0), 10),
            "spread_cost_quote": round(cost_parts.get("spread", 0.0), 10),
            "slippage_cost_quote": round(cost_parts.get("slippage", 0.0), 10),
            "execution_cost_rr": round(execution_cost_rr, 4),
            "funding_pnl_r": round(funding_pnl_r, 8),
            "funding_cost_r": round(funding_cost_r, 8),
            "funding_events_charged": funding_result["charged_events"],
            "total_cost_rr": round(execution_cost_rr + funding_cost_r, 4),
            "cost_model": ("per_fill_maker_taker_market_friction" if self.legacy_fee_rate is None else "round_trip_fee_plus_spread_slippage_proxy") + ("_plus_adverse_historical_funding" if funding_records else ""),
            "_w": net_rr > 0.0,
            "_tp": outcome.get("tp", 0),
            "_levels": outcome.get("levels") or [],
        }

    def _record(self, trade):
        self.total += 1
        self.history.append(trade)
        if trade.get("_w"):
            self.wins += 1
        closed_levels = trade.get("_levels") or []
        for level in closed_levels:
            if level == 1:
                self.tp1 += 1
            elif level == 2:
                self.tp2 += 1
            elif level == 3:
                self.tp3 += 1
        self.net_rr += trade.get("net_rr", 0.0)
        self.funding_cost_r += trade.get("funding_cost_r", 0.0)
        self.funding_events_charged += trade.get("funding_events_charged", 0)

    def performance_gate(self, minimum_trades=200, minimum_profit_factor=1.5,
                         maximum_drawdown_pct=10.0, risk_percent=1.0):
        """Historical-runner gate based only on closed, realized net-R trades."""
        trades = self.history
        net_profit = sum(max(0.0, float(item.get("net_rr", 0.0) or 0.0)) for item in trades)
        net_loss = abs(sum(min(0.0, float(item.get("net_rr", 0.0) or 0.0)) for item in trades))
        profit_factor = net_profit / net_loss if net_loss > 0 else (net_profit if net_profit > 0 else 0.0)
        equity = peak = 100.0
        max_drawdown_pct = 0.0
        risk_fraction = max(0.0, float(risk_percent)) / 100.0
        for item in trades:
            net_r = float(item.get("net_rr", 0.0) or 0.0)
            equity *= max(0.0, 1.0 + net_r * risk_fraction)
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100.0)
        sample_ok = len(trades) >= int(minimum_trades)
        pf_ok = profit_factor >= float(minimum_profit_factor)
        dd_ok = max_drawdown_pct <= float(maximum_drawdown_pct)
        return {
            "ready": bool(sample_ok and pf_ok and dd_ok),
            "sample_sufficient": sample_ok,
            "closed_trades": len(trades),
            "minimum_trades": int(minimum_trades),
            "profit_factor": round(profit_factor, 4),
            "minimum_profit_factor": float(minimum_profit_factor),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "maximum_drawdown_pct": float(maximum_drawdown_pct),
            "risk_percent_per_trade": float(risk_percent),
            "checks": {"sample": sample_ok, "profit_factor": pf_ok, "drawdown": dd_ok},
        }

    @staticmethod
    def _trade_metrics(trades):
        """Comparable gross price-path and net-after-cost metrics."""
        gross = [float(item.get("gross_rr", item.get("net_rr", 0.0)) or 0.0) for item in trades]
        net = [float(item.get("net_rr", 0.0) or 0.0) for item in trades]
        def pf(values):
            profit = sum(value for value in values if value > 0)
            loss = abs(sum(value for value in values if value < 0))
            return round(profit / loss, 4) if loss else round(profit, 4)
        count = len(trades)
        wins = sum(1 for value in net if value > 0)
        losses = sum(1 for value in net if value < 0)
        return {
            "total": count,
            "wins": wins,
            "losses": losses,
            "winrate": round(wins / count * 100.0, 2) if count else 0.0,
            "gross_rr": round(sum(gross), 4),
            "gross_expectancy": round(sum(gross) / count, 4) if count else 0.0,
            "gross_profit_factor": pf(gross),
            "net_rr": round(sum(net), 4),
            "expectancy": round(sum(net) / count, 4) if count else 0.0,
            "profit_factor": pf(net),
            "execution_cost_rr": round(sum(float(item.get("execution_cost_rr", 0.0) or 0.0) for item in trades), 4),
            "funding_cost_r": round(sum(float(item.get("funding_cost_r", 0.0) or 0.0) for item in trades), 4),
            "total_cost_rr": round(sum(float(item.get("execution_cost_rr", 0.0) or 0.0) + float(item.get("funding_cost_r", 0.0) or 0.0) for item in trades), 4),
        }

    def direction_breakdown(self):
        """Separate gross and net metrics for LONG and SHORT samples."""
        return {
            side: self._trade_metrics([item for item in self.history
                if str(item.get("direction", "")).upper() == side])
            for side in ("LONG", "SHORT")
        }

    def mtf_trade_breakdown(self):
        """Closed-trade outcomes grouped by direction and the MTF context at entry."""
        groups = {}
        for trade in self.history:
            context = trade.get("mtf_context") or {}
            direction = str(trade.get("direction") or "UNKNOWN").upper()
            key = (
                f"{direction}|weekly={str(context.get('weekly') or 'UNKNOWN').upper()}"
                f"|daily={str(context.get('daily') or 'UNKNOWN').upper()}"
                f"|h4={str(context.get('h4') or 'UNKNOWN').upper()}"
            )
            groups.setdefault(key, []).append(trade)

        return {
            key: self._trade_metrics(trades)
            for key, trades in sorted(groups.items())
        }
    def segment_breakdown(self):
        """Net performance by execution type, regime, volatility, POI and TP path."""
        dimensions = {
            "entry_type": lambda trade: trade.get("entry_type"),
            "market_phase": lambda trade: trade.get("market_phase"),
            "market_regime": lambda trade: trade.get("market_regime"),
            "volatility": lambda trade: trade.get("volatility"),
            "poi_type": lambda trade: trade.get("poi_type"),
            "tp_behavior": lambda trade: (
                "TP3" if 3 in (trade.get("_levels") or [])
                else "TP2" if 2 in (trade.get("_levels") or [])
                else "TP1_THEN_STOP" if 1 in (trade.get("_levels") or []) and "STOP" in str(trade.get("exit_reason", "")).upper()
                else "TP1_THEN_EXIT" if 1 in (trade.get("_levels") or [])
                else "STOP_BEFORE_TP1" if "STOP" in str(trade.get("exit_reason", "")).upper()
                else str(trade.get("exit_reason") or "UNKNOWN").upper()
            ),
        }
        output = {}
        for dimension, getter in dimensions.items():
            groups = {}
            for trade in self.history:
                key = str(getter(trade) or "UNKNOWN").upper()
                groups.setdefault(key, []).append(trade)
            output[dimension] = {
                key: self._trade_metrics(items)
                for key, items in sorted(groups.items())
            }
        return output

    def _microstructure_quality(self):
        samples = self.microstructure_samples
        return {
            "analysis_samples": samples,
            "archived_snapshots": self.microstructure_snapshots,
            "orderbook_snapshots": self.microstructure_orderbooks,
            "trade_snapshots": self.microstructure_trade_snapshots,
            "snapshot_coverage_pct": round(self.microstructure_snapshots / max(1, samples) * 100.0, 2),
        }
    def statistics(self):
        if not self.total:
            return {
                "total": 0, "wins": 0, "losses": 0, "winrate": 0,
                "candidate_signals": self.candidate_signals,
                "analysis_calls": self.analysis_calls,
                "empty_results": self.empty_results,
                "raw_long_signals": self.raw_long_signals,
                "raw_short_signals": self.raw_short_signals,
                "non_directional_results": self.non_directional_results,
                "action_counts": dict(self.action_counts),
                "wait_reason_counts": dict(self.wait_reason_counts),
                "signal_reason_counts": dict(self.signal_reason_counts),
                "mtf_alignment_counts": dict(self.mtf_alignment_counts),
                "entry_reason_counts": dict(self.entry_reason_counts),
                "entry_type_counts": dict(self.entry_type_counts),
                "risk_reason_counts": dict(self.risk_reason_counts),
                "target_reason_counts": dict(self.target_reason_counts),
                "target_missing_rr_counts": dict(self.target_missing_rr_counts),
                "stop_atr_buckets": dict(self.stop_atr_buckets),
                "mtf_entry_source_counts": dict(self.mtf_entry_source_counts),
                "liquidity_sweep_state_counts": dict(self.liquidity_sweep_state_counts),
                "confirmation_reason_counts": dict(self.confirmation_reason_counts),
                "confirmation_outcome_counts": dict(self.confirmation_outcome_counts),
                "confirmation_requirement_counts": dict(self.confirmation_requirement_counts),
                "entry_type_reason_counts": dict(self.entry_type_reason_counts),
                "entry_validity_counts": dict(self.entry_validity_counts),
                "decision_blocker_counts": dict(self.decision_blocker_counts),
                "direction_action_counts": dict(self.direction_action_counts),
                "direction_blocker_counts": dict(self.direction_blocker_counts),
                "unfilled_limits": self.unfilled_limits,
                "expired_limits": self.expired_limits,
                "stale_limits_cancelled": self.stale_limits_cancelled,
                "stale_limit_signal_candle_target": self.stale_limit_signal_candle_target,
                "stale_limit_target_before_fill": self.stale_limit_target_before_fill,
                "stale_limit_targets_rebased": self.stale_limit_targets_rebased,
                "stale_limit_target_rebase_rejected": self.stale_limit_target_rebase_rejected,
                "duplicate_setups_skipped": self.duplicate_setups_skipped,
                "market_fallback_fills": self.market_fallback_fills,
                "market_fallback_rejected_rr": self.market_fallback_rejected_rr,
                "market_fallback_rejected_distance": self.market_fallback_rejected_distance,
                "candidate_direction_counts": dict(self.candidate_direction_counts),
                "filled_direction_counts": dict(self.filled_direction_counts),
                "direction_fill_rates": {
                    side: round(
                        self.filled_direction_counts.get(side, 0)
                        / max(1, self.candidate_direction_counts.get(side, 0)) * 100.0, 2
                    )
                    for side in ("LONG", "SHORT")
                },
                "unfilled_limit_direction_counts": dict(self.unfilled_limit_direction_counts),
                "expired_limit_direction_counts": dict(self.expired_limit_direction_counts),
                "stale_limit_direction_counts": dict(self.stale_limit_direction_counts),
                "overlapping_signals_skipped": self.overlapping_signals_skipped,
                "trade_history": list(self.history),
                "open_trades": self.open_trades,
                "invalid_candidates": self.invalid_candidates,
                "no_followup_data": self.no_followup_data,
                "expectancy": 0, "avg_r": 0, "max_drawdown": 0,
                "profit_factor": 0, "net_rr": 0,
                "gross_profit_rr": 0, "gross_loss_rr": 0,
                "gross_rr": 0, "gross_expectancy": 0, "gross_profit_factor": 0,
                "total_execution_cost_rr": 0,
                "total_cost_rr": 0,
                "total_funding_cost_r": 0,
                "funding_events_charged": 0,
                "funding_data_quality": dict(self.funding_data_quality),
                "max_holding_bars": self.max_holding_bars,
                "microstructure_data_quality": self._microstructure_quality(),
                "entry_fee_rr": 0, "exit_fee_rr": 0, "spread_rr": 0, "slippage_rr": 0,
                "tp1": 0, "tp2": 0, "tp3": 0,
                "sample_base": "realized_closed_trades",
                "performance_gate": self.performance_gate(),
                "direction_breakdown": self.direction_breakdown(),
                "mtf_trade_breakdown": self.mtf_trade_breakdown(),
                "segment_breakdown": self.segment_breakdown(),
                "strategy_performance_breakdown": self.strategy_performance_breakdown(),
            }
        wins = self.wins
        losses = self.total - wins
        winrate = wins / self.total * 100
        gross_values = [float(h.get("gross_rr", h.get("net_rr", 0.0)) or 0.0) for h in self.history]
        net_values = [float(h.get("net_rr", 0.0) or 0.0) for h in self.history]
        gross_win = sum(value for value in gross_values if value > 0)
        gross_loss = abs(sum(value for value in gross_values if value < 0))
        net_win = sum(value for value in net_values if value > 0)
        net_loss = abs(sum(value for value in net_values if value < 0))
        gross_pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win else 0.0)
        pf = net_win / net_loss if net_loss > 0 else (net_win if net_win else 0.0)
        gross_total_rr = sum(gross_values)
        total_execution_cost_rr = sum(float(h.get("execution_cost_rr", 0.0) or 0.0) for h in self.history)
        total_funding_cost_r = sum(float(h.get("funding_cost_r", 0.0) or 0.0) for h in self.history)
        funding_events_charged = sum(int(h.get("funding_events_charged", 0) or 0) for h in self.history)

        # Max drawdown: birikimli net R eğrisinin tepe-taban farkı.
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for h in self.history:
            equity += h.get("net_rr", 0.0)
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        avg_r = self.net_rr / self.total if self.total else 0.0
        return {
            "total": self.total,
            "wins": wins,
            "candidate_signals": self.candidate_signals,
            "analysis_calls": self.analysis_calls,
            "empty_results": self.empty_results,
            "raw_long_signals": self.raw_long_signals,
            "raw_short_signals": self.raw_short_signals,
            "non_directional_results": self.non_directional_results,
            "action_counts": dict(self.action_counts),
            "wait_reason_counts": dict(self.wait_reason_counts),
            "signal_reason_counts": dict(self.signal_reason_counts),
            "mtf_alignment_counts": dict(self.mtf_alignment_counts),
            "entry_reason_counts": dict(self.entry_reason_counts),
            "entry_type_counts": dict(self.entry_type_counts),
            "risk_reason_counts": dict(self.risk_reason_counts),
            "target_reason_counts": dict(self.target_reason_counts),
            "target_missing_rr_counts": dict(self.target_missing_rr_counts),
            "stop_atr_buckets": dict(self.stop_atr_buckets),
            "mtf_entry_source_counts": dict(self.mtf_entry_source_counts),
            "liquidity_sweep_state_counts": dict(self.liquidity_sweep_state_counts),
            "confirmation_reason_counts": dict(self.confirmation_reason_counts),
            "confirmation_outcome_counts": dict(self.confirmation_outcome_counts),
            "confirmation_requirement_counts": dict(self.confirmation_requirement_counts),
            "entry_type_reason_counts": dict(self.entry_type_reason_counts),
            "entry_validity_counts": dict(self.entry_validity_counts),
            "decision_blocker_counts": dict(self.decision_blocker_counts),
            "direction_action_counts": dict(self.direction_action_counts),
            "direction_blocker_counts": dict(self.direction_blocker_counts),
            "unfilled_limits": self.unfilled_limits,
            "expired_limits": self.expired_limits,
            "stale_limits_cancelled": self.stale_limits_cancelled,
            "stale_limit_signal_candle_target": self.stale_limit_signal_candle_target,
            "stale_limit_target_before_fill": self.stale_limit_target_before_fill,
            "stale_limit_targets_rebased": self.stale_limit_targets_rebased,
            "stale_limit_target_rebase_rejected": self.stale_limit_target_rebase_rejected,
            "duplicate_setups_skipped": self.duplicate_setups_skipped,
            "market_fallback_fills": self.market_fallback_fills,
            "market_fallback_rejected_rr": self.market_fallback_rejected_rr,
            "market_fallback_rejected_distance": self.market_fallback_rejected_distance,
            "candidate_direction_counts": dict(self.candidate_direction_counts),
            "filled_direction_counts": dict(self.filled_direction_counts),
            "direction_fill_rates": {
                side: round(
                    self.filled_direction_counts.get(side, 0)
                    / max(1, self.candidate_direction_counts.get(side, 0)) * 100.0, 2
                )
                for side in ("LONG", "SHORT")
            },
            "unfilled_limit_direction_counts": dict(self.unfilled_limit_direction_counts),
            "expired_limit_direction_counts": dict(self.expired_limit_direction_counts),
            "stale_limit_direction_counts": dict(self.stale_limit_direction_counts),
            "overlapping_signals_skipped": self.overlapping_signals_skipped,
            "trade_history": list(self.history),
            "open_trades": self.open_trades,
            "invalid_candidates": self.invalid_candidates,
            "no_followup_data": self.no_followup_data,
            "losses": losses,
            "winrate": round(winrate, 2),
            "expectancy": round(self.net_rr / self.total, 4) if self.total else 0,
            "avg_r": round(avg_r, 4),
            "max_drawdown": round(max_dd, 4),
            "profit_factor": round(pf, 4),
            "gross_profit_rr": round(gross_win, 4),
            "gross_loss_rr": round(gross_loss, 4),
            "gross_rr": round(gross_total_rr, 4),
            "gross_expectancy": round(gross_total_rr / self.total, 4),
            "gross_profit_factor": round(gross_pf, 4),
            "total_execution_cost_rr": round(total_execution_cost_rr, 4),
            "total_cost_rr": round(total_execution_cost_rr + total_funding_cost_r, 4),
            "total_funding_cost_r": round(total_funding_cost_r, 4),
            "funding_events_charged": funding_events_charged,
            "funding_data_quality": dict(self.funding_data_quality),
            "max_holding_bars": self.max_holding_bars,
            "microstructure_data_quality": self._microstructure_quality(),
            "entry_fee_rr": round(sum(float(h.get("entry_fee_rr", 0.0) or 0.0) for h in self.history), 4),
            "exit_fee_rr": round(sum(float(h.get("exit_fee_rr", 0.0) or 0.0) for h in self.history), 4),
            "spread_rr": round(sum(float(h.get("spread_rr", 0.0) or 0.0) for h in self.history), 4),
            "slippage_rr": round(sum(float(h.get("slippage_rr", 0.0) or 0.0) for h in self.history), 4),
            "net_rr": round(self.net_rr, 4),
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "sample_base": "realized_closed_trades",
            "performance_gate": self.performance_gate(),
            "direction_breakdown": self.direction_breakdown(),
            "mtf_trade_breakdown": self.mtf_trade_breakdown(),
            "segment_breakdown": self.segment_breakdown(),
            "strategy_performance_breakdown": self.strategy_performance_breakdown(),
        }


TF_PERIOD_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}


def _window_up_to(candles, timestamp, tf=None):
    """Belirli bir zaman damgasına kadarki mumları döndürür.

    HTF (1h/4h/1d/1w) için look-ahead önlenir: yalnızca tamamen kapanmış
    (open_time + periyot <= timestamp) üst zaman dilimi mumları dahil edilir.
    Hâlâ oluşmakta olan HTF mumunun OHLC'si ileriye dönük bilgi sızdırdığı
    için analize alınmaz. 15m için eski davranış kullanılır.
    """
    from timing import closed_htf_candles
    return closed_htf_candles(candles, timestamp, tf)
