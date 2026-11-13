"""BTC/ETH cross-market context for altcoin entry optimization.

Correlation is evidence, not a directional veto. Strong opposing market
pressure moves the shared POI entry deeper and is reported to execution;
missing BTC/ETH data never blocks an otherwise valid structural setup.
Trend strength is normalized by ATR so different price scales are comparable.
"""

from utils.atr import atr as calculate_atr

_FALLBACK_BEAR_MULT = 0.30
_FALLBACK_BULL_MULT = 0.30
_FALLBACK_RISK_OFF_MULT = 0.30


class CorrelationEngine:
    REQUIRED_MARKETS = ("BTC", "ETH")

    def evaluate(self, symbol, direction, data):
        """Return cross-market pressure as evidence; never veto a valid SMC setup."""
        universe = data.get("correlation_universe") or data.get("market_context") or {}
        scores = {}
        for market in self.REQUIRED_MARKETS:
            candles = universe.get(market) or []
            scores[market] = self._market_bias(candles)

        is_alt = not str(symbol or "").upper().startswith(("BTC/", "ETH/"))
        direction = str(direction or "NONE").upper()
        available = [name for name, value in scores.items() if value.get("direction") != "UNKNOWN"]
        if not available or not is_alt or direction not in {"LONG", "SHORT"}:
            return {
                "active": bool(available),
                "trade_allowed": True,
                "direction": direction,
                "confidence": 50 if not available else 65,
                "counterpressure": False,
                "counterpressure_score": 0.0,
                "supportive": False,
                "markets": scores,
                "event_id": self._correlation_event_id(scores),
                "reason": "Correlation context unavailable or not applicable; no veto",
            }

        expected = "LONG" if direction == "LONG" else "SHORT"
        opposing = "SHORT" if direction == "LONG" else "LONG"
        supportive_markets = []
        opposing_markets = []
        for name in available:
            item = scores[name]
            side = item.get("direction")
            strength = float(item.get("trend_strength", 0.0) or 0.0)
            threshold = self._bear_mult() if side == "SHORT" else self._bull_mult()
            if side == expected and strength >= threshold:
                supportive_markets.append(name)
            elif side == opposing and strength >= threshold:
                opposing_markets.append(name)

        counterpressure_score = min(1.0, len(opposing_markets) / max(len(available), 1))
        supportive = bool(supportive_markets)
        counterpressure = bool(opposing_markets)
        confidence = max(25, min(90, 60 + 10 * len(supportive_markets) - 10 * len(opposing_markets)))
        reason = (
            "Cross-market counterpressure; refine POI and prefer conservative LIMIT"
            if counterpressure else
            "Cross-market support" if supportive else
            "Cross-market context is neutral"
        )
        return {
            "active": True,
            "trade_allowed": True,
            "direction": direction,
            "confidence": confidence,
            "counterpressure": counterpressure,
            "counterpressure_score": round(counterpressure_score, 3),
            "supportive": supportive,
            "supportive_markets": supportive_markets,
            "opposing_markets": opposing_markets,
            "markets": scores,
            "event_id": self._correlation_event_id(scores),
            "reason": reason,
        }

    def _bear_mult(self):
        return self._config("CORRELATION_BTC_BEAR_TREND_MULT", _FALLBACK_BEAR_MULT)

    def _bull_mult(self):
        return self._config("CORRELATION_BTC_BULL_TREND_MULT", _FALLBACK_BULL_MULT)

    def _risk_off_mult(self):
        return self._config("CORRELATION_USDT_RISK_OFF_MULT", _FALLBACK_RISK_OFF_MULT)

    def _config(self, name, default):
        try:
            from config import Config
            return float(getattr(Config, name, default))
        except Exception:
            return default

    def _correlation_event_id(self, scores):
        identities = []
        for market, item in sorted(scores.items()):
            event_id = item.get("event_id") if isinstance(item, dict) else None
            if event_id:
                identities.append(f"{market}:{event_id}")
        return "correlation:" + "|".join(identities) if identities else None

    @staticmethod
    def _candle_timestamp(candle):
        value = candle.get("time", candle.get("timestamp")) if isinstance(candle, dict) else getattr(candle, "time", None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError, OverflowError):
            return None

    def _market_bias(self, candles):
        """Trend guzun ATR-normalize edilmis fark ezeri ile olcer."""
        if not candles or len(candles) < 20:
            return {"direction": "UNKNOWN", "confidence": 0, "trend_strength": 0.0, "close": None}

        closes = [c.close for c in candles[-20:]]
        sma_fast = sum(closes[-10:]) / 10
        sma_slow = sum(closes) / 20
        atr_value = calculate_atr(candles, 14) or None
        if not atr_value or atr_value <= 0:
            atr_value = 1e-12
        diff = sma_fast - sma_slow
        trend_strength = abs(diff) / atr_value
        momentum = closes[-1] - closes[-6]

        if diff >= 0 and momentum >= 0:
            direction = "LONG"
        elif diff < 0 and momentum < 0:
            direction = "SHORT"
        else:
            direction = "NEUTRAL"

        confidence = min(95, 50 + trend_strength * 10)
        timestamp = self._candle_timestamp(candles[-1])
        event_id = f"correlation_market:{timestamp}" if timestamp is not None else None
        return {
            "event_id": event_id,
            "direction": direction,
            "confidence": int(confidence),
            "trend_strength": round(trend_strength, 3),
            "close": closes[-1],
        }