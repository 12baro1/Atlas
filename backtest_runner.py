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


def simulate_trade(entry, stop_loss, targets, future_candles, direction="LONG", round_trip_cost_rate=0.002):
    """Bir girişten itibaren sonraki mumlarda önce hangi hedefe ulaşıldığını bulur.

    future_candles: Candle nesneleri (time artan). Her mumda: low/high.
    Dönüş: {"result": "WIN"/"LOSS"/"OPEN", "tp": 1/2/3 ya da 0, "net_rr": float}
      - OPEN: verilen pencere içinde ne SL ne de TP vurulmadı (sonuç açık).
    """
    direction = (direction or "LONG").upper()
    entry = _num(entry)
    stop = _num(stop_loss)
    tp1, tp2, tp3 = _tps(targets)
    levels = [
        (level_no, target)
        for level_no, target in enumerate((tp1, tp2, tp3), start=1)
        if target is not None
    ]

    if entry is None or stop is None or not future_candles or not levels:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    risk_distance = abs(entry - stop)
    if risk_distance == 0:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    is_long = direction in ("LONG", "BUY")

    for offset, candle in enumerate(future_candles):
        low = candle.low
        high = candle.high

        if is_long:
            if low <= stop:
                return {"result": "LOSS", "tp": 0, "net_rr": _num(-1.0),
                        "exit_reason": "STOP", "exit_offset": offset}
            for level_no, tp in levels:
                if high >= tp:
                    rr = abs(tp - entry) / risk_distance
                    return {"result": "WIN", "tp": level_no, "net_rr": _num(rr),
                            "exit_reason": f"TP{level_no}", "exit_offset": offset}
        else:
            if high >= stop:
                return {"result": "LOSS", "tp": 0, "net_rr": _num(-1.0),
                        "exit_reason": "STOP", "exit_offset": offset}
            for level_no, tp in levels:
                if low <= tp:
                    rr = abs(entry - tp) / risk_distance
                    return {"result": "WIN", "tp": level_no, "net_rr": _num(rr),
                            "exit_reason": f"TP{level_no}", "exit_offset": offset}

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
):
    """Kısmi TP ve gecikmeli trailing-stop simülasyonu.

    TP ağırlıkları normalize edilir. Bir mumda yalnızca sıradaki tek hedef
    gerçekleşmiş sayılır; OHLC verisi TP1→TP2 sırasını kanıtlayamaz.
    TP1 sonrası breakeven, TP2 sonrası TP1 stopu bir sonraki mumdan itibaren
    etkinleşir. Stopta gap varsa gerçekleşme fiyatı mum açılışıdır.
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
    next_level_idx = 0
    reached_tp = 0
    trailing_stop = stop
    exit_reason = None
    exit_offset = None

    for candle_offset, candle in enumerate(future_candles):
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
            break

        # OHLC mumunda hedeflerin sırası bilinemez: mum başına yalnızca bir TP say.
        if next_level_idx < len(levels):
            level_no, tp_price = levels[next_level_idx]
            hit = high >= tp_price if is_long else low <= tp_price
            if hit:
                weight = weights[next_level_idx]
                rr = abs(tp_price - entry) / risk_distance
                realized_rr += weight * rr
                closed_frac += weight
                reached_tp = level_no
                next_level_idx += 1

                # Yeni trailing stop sonraki mumda aktif olur.
                available = {number for number, _ in levels}
                if level_no == 1 and len(levels) > 1:
                    trailing_stop = entry
                elif level_no == 2 and 1 in available and 3 in available:
                    trailing_stop = next(price for number, price in levels if number == 1)

                if closed_frac >= 1.0 - 1e-9:
                    exit_reason = f"TP{reached_tp}"
                    exit_offset = candle_offset
                    break

    if closed_frac < 1.0 - 1e-9:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    result = "WIN" if realized_rr > 0.0 else "LOSS"
    return {
        "result": result,
        "tp": reached_tp,
        "net_rr": _num(realized_rr, 4),
        "levels": [level_no for level_no, _ in levels[:next_level_idx]],
        "exit_reason": exit_reason,
        "exit_offset": exit_offset,
    }

class BacktestRunner:
    """Fiyat serisini ileri sararak engine sinyallerini tetikler ve sonuç toplar."""

    def __init__(self, analyze_fn=None, fee_rate=0.0020, partial_exits=True, tp_weights=None,
                 limit_expiry_bars=8):
        self.analyze_fn = analyze_fn
        self.fee_rate = float(fee_rate)
        self.partial_exits = bool(partial_exits)
        self.tp_weights = tp_weights
        self.limit_expiry_bars = max(1, int(limit_expiry_bars))
        self.full_exit_calls = 0
        self.history = []
        self.total = 0
        self.wins = 0
        self.candidate_signals = 0
        self.unfilled_limits = 0
        self.expired_limits = 0
        self.stale_limits_cancelled = 0
        self.open_trades = 0
        self.invalid_candidates = 0
        self.no_followup_data = 0
        self.tp1 = 0
        self.tp2 = 0
        self.tp3 = 0
        self.net_rr = 0.0
        # Diagnostic counters explain why historical analysis produces no trades.
        self.analysis_calls = 0
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
        self.entry_validity_counts = {}
        self.decision_blocker_counts = {}

    def reset(self):
        self.__init__(
            analyze_fn=self.analyze_fn,
            fee_rate=self.fee_rate,
            partial_exits=self.partial_exits,
            tp_weights=self.tp_weights,
            limit_expiry_bars=self.limit_expiry_bars,
        )

    def run(self, data, on_signal=None, step=1, lenient=False):
        """data: {'15m': [Candle,...], '1h': [...], ...} -> her mum sonrası analiz + simülasyon.

        lenient=True ise decision kapısı atlanır; sinyal yönü LONG/SHORT ve entry geçerliyse
        işlem üretilir (ham sinyalin edge'i ölçülür).
        """
        candles = data.get("15m") or data.get("15M")
        if not candles:
            return self.statistics()

        total = len(candles)
        warmup = 300
        for idx in range(warmup, total, max(1, step)):
            # Signal decision is made at the close of the current 15m candle.
            decision_time_ms = candles[idx].time + 15 * 60 * 1000
            window = {
                tf: candles[: idx + 1] if tf == "15m" else _window_up_to(data.get(tf), decision_time_ms, tf)
                for tf in ("15m", "1h", "4h", "1d", "1w")
            }
            window["symbol"] = data.get("symbol", "SYMBOL")

            self.analysis_calls += 1
            result = self.analyze_fn(window) if self.analyze_fn else on_signal(window)

            if not result:
                self.empty_results += 1
                continue
            signal = (result.get("signal") or {}) if isinstance(result, dict) else {}
            decision = (result.get("decision") or {}) if isinstance(result, dict) else {}
            signal_dir = str(signal.get("signal", "")).upper()
            action = str(decision.get("action", "MISSING")).upper() or "MISSING"
            self.action_counts[action] = self.action_counts.get(action, 0) + 1
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
            confirmation_meta = (analysis or {}).get("confirmation") if isinstance(analysis, dict) else {}
            if isinstance(confirmation_meta, dict):
                reason = str(confirmation_meta.get("reason") or "unspecified")
                self.confirmation_reason_counts[reason] = self.confirmation_reason_counts.get(reason, 0) + 1
            entry_meta = (analysis or {}).get("entry") if isinstance(analysis, dict) else {}
            if isinstance(entry_meta, dict):
                entry_reason = str(entry_meta.get("entry_reason_code") or entry_meta.get("reason") or "unspecified")
                self.entry_reason_counts[entry_reason] = self.entry_reason_counts.get(entry_reason, 0) + 1
                entry_type = str(entry_meta.get("entry_type") or "NONE").upper()
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
            risk_meta = result.get("risk") if isinstance(result, dict) else {}
            if isinstance(risk_meta, dict) and risk_meta.get("risk_setup_valid") is False:
                risk_reason = str(risk_meta.get("reason_code") or risk_meta.get("risk_setup_reason") or "unspecified")
                self.risk_reason_counts[risk_reason] = self.risk_reason_counts.get(risk_reason, 0) + 1
            if isinstance(risk_meta, dict):
                atr_value = _num(risk_meta.get("atr"))
                stop_distance = _num(risk_meta.get("requested_risk"))
                if stop_distance is None:
                    stop_distance = _num(risk_meta.get("risk"))
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
            trade = self._to_trade(result, candles, idx + 1, lenient=lenient, signal_index=idx)
            if trade is None:
                continue
            self._record(trade)

        return self.statistics()

    def _to_trade(self, result, candles, entry_index, lenient=False, signal_index=None):
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
        self.candidate_signals += 1

        risk = (result or {}).get("risk") or {}
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

            # A LIMIT is submitted only after the signal candle closes. If a
            # structural target was already touched during that candle, the
            # pending order is stale before it even exists.
            if signal_index is not None and 0 <= signal_index < entry_index and signal_index < len(candles):
                signal_candle = candles[signal_index]
                target_hit_before_order = any(
                    (signal_candle.high >= target if is_long else signal_candle.low <= target)
                    for target in (_num(risk.get("tp1")), _num(risk.get("tp2")), _num(risk.get("tp3")))
                    if target is not None
                )
                if target_hit_before_order:
                    self.stale_limits_cancelled += 1
                    return None

            expiry_index = min(len(candles), entry_index + self.limit_expiry_bars)
            for candidate_index in range(entry_index, expiry_index):
                candle = candles[candidate_index]
                opened = _num(candle.open)
                if opened is None:
                    continue
                gap_fill = (opened <= limit_price) if is_long else (opened >= limit_price)
                touched = candle.low <= limit_price if is_long else candle.high >= limit_price
                target_already_hit = any(
                    (candle.high >= target if is_long else candle.low <= target)
                    for target in (_num(risk.get('tp1')), _num(risk.get('tp2')), _num(risk.get('tp3')))
                    if target is not None
                )
                # If a target is reached on a candle that never touches the
                # pending entry, cancel the stale order. If both are touched
                # in one candle, OHLC cannot reveal the path: keep the fill but
                # apply the conservative fill-candle handling below.
                if target_already_hit and not touched:
                    self.stale_limits_cancelled += 1
                    return None
                if not touched:
                    continue
                entry_price = min(limit_price, opened) if is_long else max(limit_price, opened)
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
                self.unfilled_limits += 1
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

        use_partial = bool(getattr(self, "partial_exits", True))
        if limit_intrabar_fill:
            fill_candle = candles[fill_index]
            fill_stop_hit = _candle_touched_stop(
                signal_dir == "LONG", stop, fill_candle.low, fill_candle.high
            )
            if fill_stop_hit:
                outcome = {"result": "LOSS", "tp": 0, "net_rr": -1.0, "levels": [],
                           "exit_reason": "STOP", "exit_offset": 0}
                outcome_start_index = fill_index
            else:
                # Exclude the fill candle from target simulation. Its high/low
                # may have occurred before the intrabar limit order was filled.
                future = candles[fill_index + 1:]
                outcome_start_index = fill_index + 1
                if use_partial:
                    outcome = simulate_trade_partial(
                        entry=entry_price,
                        stop_loss=stop,
                        targets=tps,
                        future_candles=future,
                        direction=signal_dir,
                        tp_weights=self.tp_weights,
                    )
                else:
                    outcome = simulate_trade(
                        entry=entry_price,
                        stop_loss=stop,
                        targets=tps,
                        future_candles=future,
                        direction=signal_dir,
                        round_trip_cost_rate=self.fee_rate,
                    )
        else:
            # MARKET and gap-through LIMIT orders fill at candle open.
            future = candles[fill_index:]
            outcome_start_index = fill_index
            if use_partial:
                outcome = simulate_trade_partial(
                    entry=entry_price,
                    stop_loss=stop,
                    targets=tps,
                    future_candles=future,
                    direction=signal_dir,
                    tp_weights=self.tp_weights,
                )
            else:
                outcome = simulate_trade(
                    entry=entry_price,
                    stop_loss=stop,
                    targets=tps,
                    future_candles=future,
                    direction=signal_dir,
                    round_trip_cost_rate=self.fee_rate,
                )

        # Pencere içinde çözülemeyen (ne SL ne TP) işlemleri istatistiğe katma.
        if outcome.get("result") == "OPEN":
            self.open_trades += 1
            return None

        risk_distance = abs(entry_price - stop)
        # fee_rate is ROUND-TRIP cost (same meaning as Config.ROUND_TRIP_COST_RATE).
        fee_rr = (abs(entry_price) * self.fee_rate) / risk_distance if risk_distance > 0 else self.fee_rate
        base_rr = outcome.get("net_rr", 0.0)
        if not use_partial:
            if outcome.get("result") == "WIN":
                base_rr = max(0.0, base_rr - fee_rr)
            else:
                base_rr = -(1.0 + fee_rr)
        else:
            # Kısmi modelde her parça kapanışında fee ayrı ayrı işlemiştir
            # (simulate_trade_partial gerçekleşen R'a gayret etmez); burada
            # pozisyon başına gerçekleşen ağırlıklı R'den tek turluk fee düşülür.
            base_rr = round(base_rr - fee_rr, 4)
        net_rr = base_rr

        signal_index = max(0, int(signal_index if signal_index is not None else entry_index - 1))
        exit_offset = outcome.get("exit_offset")
        exit_index = (outcome_start_index + int(exit_offset)
                      if exit_offset is not None else None)
        exit_time = int(candles[exit_index].time) if exit_index is not None and exit_index < len(candles) else None
        return {
            "signal_index": signal_index,
            "signal_time": int(candles[signal_index].time),
            "entry_index": fill_index,
            "entry_time": int(candles[fill_index].time),
            "fill_delay_bars": max(0, fill_index - entry_index),
            "entry_type": entry_type,
            "planned_entry": _num(planned_entry),
            "direction": signal_dir,
            "entry": entry_price,
            "stop_loss": stop,
            "tps": tps,
            "exit_reason": outcome.get("exit_reason", "UNKNOWN"),
            "exit_index": exit_index,
            "exit_time": exit_time,
            "result": outcome.get("result"),
            "tp": outcome.get("tp", 0),
            "net_rr": round(max(net_rr, -99.0), 4),
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

    def performance_gate(self, minimum_trades=200, minimum_profit_factor=1.5,
                         maximum_drawdown_pct=10.0, risk_percent=1.0):
        """Historical-runner gate based only on closed, realized net-R trades."""
        trades = self.history
        gross_profit = sum(max(0.0, float(item.get("net_rr", 0.0) or 0.0)) for item in trades)
        gross_loss = abs(sum(min(0.0, float(item.get("net_rr", 0.0) or 0.0)) for item in trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
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

    def direction_breakdown(self):
        """Separate realized metrics for LONG and SHORT samples."""
        output = {}
        for side in ("LONG", "SHORT"):
            trades = [item for item in self.history if str(item.get("direction", "")).upper() == side]
            wins = [item for item in trades if float(item.get("net_rr", 0.0) or 0.0) > 0]
            losses = [item for item in trades if float(item.get("net_rr", 0.0) or 0.0) < 0]
            gross_profit = sum(float(item.get("net_rr", 0.0) or 0.0) for item in wins)
            gross_loss = abs(sum(float(item.get("net_rr", 0.0) or 0.0) for item in losses))
            output[side] = {
                "total": len(trades),
                "wins": len(wins),
                "losses": len(losses),
                "winrate": round(len(wins) / len(trades) * 100.0, 2) if trades else 0.0,
                "expectancy": round(sum(float(item.get("net_rr", 0.0) or 0.0) for item in trades) / len(trades), 4) if trades else 0.0,
                "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit else 0.0),
            }
        return output

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
                "entry_validity_counts": dict(self.entry_validity_counts),
                "decision_blocker_counts": dict(self.decision_blocker_counts),
                "unfilled_limits": self.unfilled_limits,
                "expired_limits": self.expired_limits,
                "stale_limits_cancelled": self.stale_limits_cancelled,
                "trade_history": list(self.history),
                "open_trades": self.open_trades,
                "invalid_candidates": self.invalid_candidates,
                "no_followup_data": self.no_followup_data,
                "expectancy": 0, "avg_r": 0, "max_drawdown": 0,
                "profit_factor": 0, "net_rr": 0,
                "gross_profit_rr": 0, "gross_loss_rr": 0,
                "tp1": 0, "tp2": 0, "tp3": 0,
                "sample_base": "realized_closed_trades",
                "performance_gate": self.performance_gate(),
                "direction_breakdown": self.direction_breakdown(),
            }
        wins = self.wins
        losses = self.total - wins
        winrate = wins / self.total * 100
        gross_win = sum(h.get("net_rr", 0.0) for h in self.history if h.get("_w"))
        gross_loss = abs(sum(h.get("net_rr", 0.0) for h in self.history if not h.get("_w")))
        pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win else 0.0)

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
            "entry_validity_counts": dict(self.entry_validity_counts),
            "decision_blocker_counts": dict(self.decision_blocker_counts),
            "unfilled_limits": self.unfilled_limits,
            "expired_limits": self.expired_limits,
            "stale_limits_cancelled": self.stale_limits_cancelled,
            "trade_history": list(self.history),
            "open_trades": self.open_trades,
            "invalid_candidates": self.invalid_candidates,
            "no_followup_data": self.no_followup_data,
            "losses": losses,
            "winrate": round(winrate, 2),
            "expectancy": round(self.net_rr / self.total, 4) if self.total else 0,
            "avg_r": round(avg_r, 4),
            "max_drawdown": round(max_dd, 4),
            "profit_factor": round(pf, 2),
            "gross_profit_rr": round(gross_win, 4),
            "gross_loss_rr": round(gross_loss, 4),
            "net_rr": round(self.net_rr, 2),
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "sample_base": "realized_closed_trades",
            "performance_gate": self.performance_gate(),
            "direction_breakdown": self.direction_breakdown(),
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
