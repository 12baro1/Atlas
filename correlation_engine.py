"""Market correlation guard for BTC/ETH dominance-aware altcoin signals."""

from utils.atr import atr as calculate_atr


class CorrelationEngine:
    REQUIRED_MARKETS = ("BTC", "ETH", "BTC.D", "USDT.D", "TOTAL3")

    def evaluate(self, symbol, direction, data):
        universe = data.get("correlation_universe") or data.get("market_context") or {}
        scores = {}
        for market in self.REQUIRED_MARKETS:
            candles = universe.get(market) or universe.get(market.replace(".D", "_DOMINANCE")) or []
            scores[market] = self._market_bias(candles)
        is_alt = not str(symbol).upper().startswith(("BTC/", "ETH/"))
        btc_supports_long = scores["BTC"].get("direction") == "LONG"
        usdt_risk_off = scores["USDT.D"].get("direction") == "LONG"
        total3_supports = scores["TOTAL3"].get("direction") == direction
        blocker = False
        reason = "Correlation context acceptable"
        if is_alt and direction == "LONG" and (not btc_supports_long or usdt_risk_off):
            blocker = True
            reason = "Altcoin LONG blocked by BTC/USDT dominance context"
        if is_alt and direction == "SHORT" and total3_supports is False and scores["BTC"].get("direction") == "LONG":
            blocker = True
            reason = "Altcoin SHORT blocked by broad market strength"
        confidence = 75
        if blocker:
            confidence = 20
        elif total3_supports or not is_alt:
            confidence = 85
        return {
            "active": bool(universe),
            "trade_allowed": not blocker,
            "direction": direction,
            "confidence": confidence,
            "markets": scores,
            "reason": reason,
        }

    def _market_bias(self, candles):
        if not candles or len(candles) < 20:
            return {"direction": "UNKNOWN", "confidence": 0}
        last = candles[-1]
        sma_fast = sum(c.close for c in candles[-10:]) / 10
        sma_slow = sum(c.close for c in candles[-20:]) / 20
        atr_value = calculate_atr(candles, 14)
        momentum = last.close - candles[-5].close
        direction = "LONG" if sma_fast >= sma_slow and momentum >= 0 else "SHORT"
        confidence = min(95, 50 + abs(sma_fast - sma_slow) / max(atr_value, 1e-12) * 10)
        return {"direction": direction, "confidence": int(confidence), "close": last.close}
