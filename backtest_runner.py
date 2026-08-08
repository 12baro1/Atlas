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

logger = logging.getLogger("atlas.backtest_runner")


def _num(value, digits=4):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


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
    tps = [tp for tp in (tp1, tp2, tp3) if tp is not None]

    if entry is None or stop is None or not future_candles or not tps:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    risk_distance = abs(entry - stop)
    if risk_distance == 0:
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    is_long = direction in ("LONG", "BUY")

    for candle in future_candles:
        low = candle.low
        high = candle.high

        if is_long:
            if low <= stop:
                return {"result": "LOSS", "tp": 0, "net_rr": _num(-1.0)}
            for idx, tp in enumerate(tps, start=1):
                if tp is not None and high >= tp:
                    rr = abs(tp - entry) / risk_distance
                    return {"result": "WIN", "tp": idx, "net_rr": _num(rr)}
        else:
            if high >= stop:
                return {"result": "LOSS", "tp": 0, "net_rr": _num(-1.0)}
            for idx, tp in enumerate(tps, start=1):
                if tp is not None and low <= tp:
                    rr = abs(entry - tp) / risk_distance
                    return {"result": "WIN", "tp": idx, "net_rr": _num(rr)}

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
    """KISMİ ÇIKIŞ modeli: pozisyon TP seviyelerinde parsellere ayrılır.

    Varsayılan ağırlıklar: mevcut TP sayısına eşit bölünür (1 TP %100, 2 TP
    %50/%50, 3 TP %33.3/%33.3/%33.3). Her TP kapanışında açık kısmın stopu
    bir sonraki koruma seviyesine (breakeven ya da bir önceki TP) taşınır.
    Amaç: TP1 sonrası SL (kısmi kazanç geri verilmeden), TP1→TP2/TP3 devam
    senaryosunu gerçekçi şekilde modellemek.

    Dönüş: {"result": "WIN"/"LOSS"/"OPEN", "tp": ulaşılan en yüksek seviye,
            "net_rr": gerçekleşen ağırlıklı R}
      - WINRATE yalnızca TAMAMEN gerçekleşen (kapanan) işlemlerden hesaplanır;
        pencere bitmeden pozisyon kapanmazsa "OPEN" → istatistiğe girmez.
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

    # Ağırlıklar: geçilmezse TP sayısına göre eşit bölünür (toplam = 1.0).
    n = len(levels)
    if tp_weights and isinstance(tp_weights, dict):
        weights = [float(tp_weights.get(f"tp{level_no}", 0.0)) for level_no, _ in levels]
    else:
        weights = [1.0 / n] * n
    total_w = sum(weights)
    if total_w <= 0:
        weights = [1.0 / n] * n
        total_w = 1.0
    weights = [w / total_w for w in weights]  # normalize

    is_long = direction in ("LONG", "BUY")

    realized_rr = 0.0
    closed_frac = 0.0
    next_level_idx = 0
    reached_tp = 0
    trailing_stop = stop

    for candle in future_candles:
        low = candle.low
        high = candle.high

        # 1) Stop önceliği: kalan pozisyon önce SL'den çıkar.
        sl_hit = _candle_touched_stop(is_long, trailing_stop, low, high)
        if sl_hit:
            remaining = 1.0 - closed_frac
            if remaining > 0.0:
                # Stop seviyesine göre R: breakeven'de 0R, orijinal SL'de -1R,
                # pozitif taşınan stoplarda (TP1 eşiği) +R doğru modellenir.
                if is_long:
                    rr_stop = (trailing_stop - entry) / risk_distance
                else:
                    rr_stop = (entry - trailing_stop) / risk_distance
                realized_rr += remaining * rr_stop
                closed_frac = 1.0
            break

        # 2) TP seviyelerine en yakından başlayarak kısmi çıkış.
        while next_level_idx < len(levels):
            level_no, tp_price = levels[next_level_idx]
            hit = (high >= tp_price) if is_long else (low <= tp_price)
            if not hit:
                break
            weight = weights[next_level_idx]
            rr = abs(tp_price - entry) / risk_distance
            realized_rr += weight * rr
            closed_frac += weight
            reached_tp = level_no
            next_level_idx += 1
            # Koruma stopunu taşınma: TP1 → breakeven, TP2 → TP1 seviyesi.
            if next_level_idx == 1 and len(levels) > 1:
                trailing_stop = entry
            elif next_level_idx == n:
                trailing_stop = levels[0][1] if n >= 2 else entry

        if closed_frac >= 1.0 - 1e-9:
            break

    if closed_frac < 1.0 - 1e-9:
        # Pencere içinde pozisyon tam kapanmadı: gerçekleşmemiş, istatistiğe girmez.
        return {"result": "OPEN", "tp": 0, "net_rr": 0.0}

    result = "WIN" if realized_rr > 0.0 else "LOSS"
    return {
        "result": result,
        "tp": reached_tp,
        "net_rr": _num(realized_rr, 4),
        "levels": [level_no for level_no, _ in levels[:next_level_idx]],
    }


class BacktestRunner:
    """Fiyat serisini ileri sararak engine sinyallerini tetikler ve sonuç toplar."""

    def __init__(self, analyze_fn=None, fee_rate=0.0020, partial_exits=True, tp_weights=None):
        self.analyze_fn = analyze_fn
        self.fee_rate = float(fee_rate)
        self.partial_exits = bool(partial_exits)
        self.tp_weights = tp_weights
        self.full_exit_calls = 0
        self.history = []
        self.total = 0
        self.wins = 0
        self.tp1 = 0
        self.tp2 = 0
        self.tp3 = 0
        self.net_rr = 0.0

    def reset(self):
        self.__init__(
            analyze_fn=self.analyze_fn,
            fee_rate=self.fee_rate,
            partial_exits=self.partial_exits,
            tp_weights=self.tp_weights,
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
            window = {tf: candles[: idx + 1] if tf == "15m" else _window_up_to(data.get(tf), candles[idx].time, tf)
                      for tf in ("15m", "1h", "4h", "1d", "1w")}
            window["symbol"] = data.get("symbol", "SYMBOL")

            result = self.analyze_fn(window) if self.analyze_fn else on_signal(window)

            if not result:
                continue
            trade = self._to_trade(result, candles, idx + 1, lenient=lenient)
            if trade is None:
                continue
            self._record(trade)

        return self.statistics()

    def _to_trade(self, result, candles, entry_index, lenient=False):
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

        risk = (result or {}).get("risk") or {}
        if isinstance(risk, dict) and risk.get("risk_setup_valid") is False:
            return None

        entry_price = risk.get("entry")
        stop = risk.get("stop_loss")
        if entry_price is None or stop is None:
            return None

        tps = [risk.get("tp1"), risk.get("tp2"), risk.get("tp3")]
        future = candles[entry_index:]
        use_partial = bool(getattr(self, "partial_exits", True))
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
            return None

        risk_distance = abs(entry_price - stop)
        fee_rr = (abs(entry_price) * self.fee_rate * 2) / risk_distance if risk_distance > 0 else self.fee_rate * 2
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

        return {
            "entry_index": entry_index,
            "direction": signal_dir,
            "entry": entry_price,
            "stop_loss": stop,
            "tps": tps,
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

    def statistics(self):
        if not self.total:
            return {
                "total": 0, "wins": 0, "losses": 0, "winrate": 0,
                "expectancy": 0, "avg_r": 0, "max_drawdown": 0,
                "profit_factor": 0, "net_rr": 0,
                "tp1": 0, "tp2": 0, "tp3": 0,
                "sample_base": "realized_closed_trades",
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
            "losses": losses,
            "winrate": round(winrate, 2),
            "expectancy": round(self.net_rr / self.total, 4) if self.total else 0,
            "avg_r": round(avg_r, 4),
            "max_drawdown": round(max_dd, 4),
            "profit_factor": round(pf, 2),
            "net_rr": round(self.net_rr, 2),
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "sample_base": "realized_closed_trades",
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
