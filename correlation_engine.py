"""Market correlation guard for BTC/ETH dominance-aware altcoin signals.

Altcoin LONG sinyalleri yalnizca "gercekten" riskli bir ortamda engellenir:
  - BTC guclu bir dusus trendinde degilse LONG engellenmez,
  - USDT.D (risk-off) yukseliyor ve guc esigi asiliyorsa engellenir,
  - veri yoksa (universe bos/eksik) sistem otomatik olarak LONG/SHORT'u
    engellemez; noral kabul edilerek sinyalin normal karar surecinden
    gecmesine izin verir.

Trend gucu ATR-ile-normalize edilmis fiyat sapmasiyla olculur ve esikler
Config'ten okunur. Eski davranis (universe bosken bile her Altcoin LONG'unu
engelleme) duzeltildi: veri yokken ve trend zayifken engel yok.
"""

from utils.atr import atr as calculate_atr

_FALLBACK_BEAR_MULT = 0.30
_FALLBACK_BULL_MULT = 0.30
_FALLBACK_RISK_OFF_MULT = 0.30


class CorrelationEngine:
    REQUIRED_MARKETS = ("BTC", "ETH", "BTC.D", "USDT.D", "TOTAL3")

    def evaluate(self, symbol, direction, data):
        universe = data.get("correlation_universe") or data.get("market_context") or {}
        scores = {}
        available = 0
        for market in self.REQUIRED_MARKETS:
            candles = universe.get(market) or universe.get(market.replace(".", "_")) or []
            bias = self._market_bias(candles)
            scores[market] = bias
            if bias.get("direction") != "UNKNOWN":
                available += 1

        is_alt = not str(symbol or "").upper().startswith(("BTC/", "ETH/"))
        btc = scores.get("BTC", {})
        risk_off = scores.get("USDT.D", {})
        total3 = scores.get("TOTAL3", {})

        direction = direction or "NONE"

        if available == 0:
            return {
                "active": False,
                "trade_allowed": True,
                "confidence": 75,
                "reason": "Correlation engine inactive (no market data provided)",
                "direction": direction,
                "markets": scores,
            }

        blocker = False
        reason = "Correlation context acceptable"

        if is_alt and direction == "LONG":
            btc_strong_bear = (
                btc.get("direction") == "SHORT"
                and btc.get("trend_strength", 0.0) >= self._bear_mult()
            )
            usdt_risk_off = (
                risk_off.get("direction") == "LONG"
                and risk_off.get("trend_strength", 0.0) >= self._risk_off_mult()
            )
            if btc_strong_bear or usdt_risk_off:
                blocker = True
                reason = "Altcoin LONG blocked: strong BTC downtrend or USDT risk-off"

        if is_alt and direction == "SHORT":
            btc_strong_bull = (
                btc.get("direction") == "LONG"
                and btc.get("trend_strength", 0.0) >= self._bull_mult()
            )
            # "Broad market strength" = TOTAL3 yükselişte (LONG). Düşen total3
            # ALT-SHORT'un kendisiyle hizalıdır, blok değil.
            total3_bull = total3.get("direction") == "LONG"
            if btc_strong_bull and total3_bull:
                blocker = True
                reason = "Altcoin SHORT blocked: broad market strength"

        confidence = 75
        if blocker:
            confidence = 20
        elif not is_alt or total3.get("direction") == direction:
            confidence = 85

        return {
            "active": True,
            "trade_allowed": not blocker,
            "direction": direction,
            "confidence": confidence,
            "markets": scores,
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
        return {
            "direction": direction,
            "confidence": int(confidence),
            "trend_strength": round(trend_strength, 3),
            "close": closes[-1],
        }