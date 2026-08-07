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
    Dönüş: {"result": "WIN"/"LOSS", "tp": 1/2/3 ya da 0, "net_rr": float}
    """
    direction = (direction or "LONG").upper()
    entry = _num(entry)
    stop = _num(stop_loss)
    tp1, tp2, tp3 = _tps(targets)
    tps = [tp for tp in (tp1, tp2, tp3) if tp is not None]

    if entry is None or stop is None or not future_candles or not tps:
        return {"result": "LOSS", "tp": 0, "net_rr": 0.0}

    risk_distance = abs(entry - stop)
    if risk_distance == 0:
        return {"result": "LOSS", "tp": 0, "net_rr": 0.0}

    is_long = direction in ("LONG", "BUY")

    for candle in future_candles:
        low = candle.low
        high = candle.high

        if is_long:
            if low <= stop:
                return {"result": "LOSS", "tp": 0, "net_rr": _num(-1.0)}
            for idx, tp in enumerate(tps, start=1):
                if tp is not None and low <= tp <= high:
                    rr = abs(tp - entry) / risk_distance
                    return {"result": "WIN", "tp": idx, "net_rr": _num(rr)}
        else:
            if high >= stop:
                return {"result": "LOSS", "tp": 0, "net_rr": _num(-1.0)}
            for idx, tp in enumerate(tps, start=1):
                if tp is not None and low <= tp <= high:
                    rr = abs(entry - tp) / risk_distance
                    return {"result": "WIN", "tp": idx, "net_rr": _num(rr)}

    return {"result": "LOSS", "tp": 0, "net_rr": 0.0}


class BacktestRunner:
    """Fiyat serisini ileri sararak engine sinyallerini tetikler ve sonuç toplar."""

    def __init__(self, analyze_fn=None, fee_rate=0.0020):
        self.analyze_fn = analyze_fn
        self.fee_rate = float(fee_rate)
        self.history = []
        self.total = 0
        self.wins = 0
        self.tp1 = 0
        self.tp2 = 0
        self.tp3 = 0
        self.net_rr = 0.0

    def reset(self):
        self.__init__(analyze_fn=self.analyze_fn, fee_rate=self.fee_rate)

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
            window = {tf: candles[: idx + 1] if tf == "15m" else _window_up_to(data.get(tf), candles[idx].time)
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
        entry_price = risk.get("entry")
        stop = risk.get("stop_loss")
        if entry_price is None or stop is None:
            return None

        tps = [risk.get("tp1"), risk.get("tp2"), risk.get("tp3")]
        future = candles[entry_index:]
        outcome = simulate_trade(
            entry=entry_price,
            stop_loss=stop,
            targets=tps,
            future_candles=future,
            direction=signal_dir,
            round_trip_cost_rate=self.fee_rate,
        )
        net_rr = outcome.get("net_rr", 0.0)
        # Round-trip maliyetini beklenti hesabına yansıt
        if outcome.get("result") == "WIN":
            net_rr = max(0.0, net_rr - self.fee_rate * 2)
        else:
            net_rr = -(1.0 + self.fee_rate * 2)

        return {
            "entry_index": entry_index,
            "direction": signal_dir,
            "entry": entry_price,
            "stop_loss": stop,
            "tps": tps,
            "result": outcome.get("result"),
            "tp": outcome.get("tp", 0),
            "net_rr": round(net_rr, 4),
            "_w": outcome.get("result") == "WIN",
            "_tp": outcome.get("tp", 0),
        }

    def _record(self, trade):
        self.total += 1
        self.history.append(trade)
        if trade.get("_w"):
            self.wins += 1
        tp = trade.get("_tp", 0)
        if tp == 1:
            self.tp1 += 1
        elif tp == 2:
            self.tp2 += 1
        elif tp == 3:
            self.tp3 += 1
        self.net_rr += trade.get("net_rr", 0.0)

    def statistics(self):
        if not self.total:
            return {
                "total": 0, "wins": 0, "losses": 0, "winrate": 0,
                "expectancy": 0, "profit_factor": 0, "net_rr": 0,
                "tp1": 0, "tp2": 0, "tp3": 0,
            }
        wins = self.wins
        losses = self.total - wins
        winrate = wins / self.total * 100
        gross_win = sum(h.get("net_rr", 0.0) for h in self.history if h.get("_w"))
        gross_loss = abs(sum(h.get("net_rr", 0.0) for h in self.history if not h.get("_w")))
        pf = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win else 0.0)
        return {
            "total": self.total,
            "wins": wins,
            "losses": losses,
            "winrate": round(winrate, 2),
            "expectancy": round(self.net_rr / self.total, 4) if self.total else 0,
            "profit_factor": round(pf, 2),
            "net_rr": round(self.net_rr, 2),
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
        }


def _window_up_to(candles, timestamp):
    """Belirli bir zaman damgasına kadar olan mumları döndürür."""
    if not candles:
        return []
    out = []
    for c in candles:
        if c.time > timestamp:
            break
        out.append(c)
    return out
