"""OHLCV-only market regime classification for Atlas.

This engine deliberately uses only closed candle data. It does not infer
order flow, liquidation levels, or other unavailable exchange microstructure.
"""

import math
from statistics import median


class MarketRegimeEngine:
    """Classify trend, range, compression and volatility from OHLCV candles."""

    MIN_CANDLES = 50

    def analyze(self, candles):
        if not candles or len(candles) < self.MIN_CANDLES:
            return self._unknown("Insufficient candle history")

        try:
            rows = [
                (float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume))
                for c in candles[-80:]
            ]
        except (AttributeError, TypeError, ValueError, OverflowError):
            return self._unknown("Malformed candle data")

        if any(
            not all(math.isfinite(value) for value in row)
            or high < max(open_, close, low)
            or low > min(open_, close, high)
            or min(open_, high, low, close) <= 0
            or volume < 0
            for open_, high, low, close, volume in rows
        ):
            return self._unknown("Invalid or non-finite OHLCV values")

        closes = [row[3] for row in rows]
        true_ranges = []
        for index, row in enumerate(rows):
            _, high, low, _, _ = row
            previous_close = closes[index - 1] if index else closes[index]
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

        atr_fast = sum(true_ranges[-14:]) / 14
        atr_slow = sum(true_ranges[-50:]) / 50
        if not math.isfinite(atr_fast) or not math.isfinite(atr_slow) or atr_fast <= 0 or atr_slow <= 0:
            return self._unknown("ATR unavailable")

        # Efficiency ratio: directional travel divided by total path length.
        changes = [abs(closes[i] - closes[i - 1]) for i in range(len(closes) - 20, len(closes))]
        path = sum(changes)
        efficiency = abs(closes[-1] - closes[-21]) / path if path > 0 else 0.0

        # Least-squares slope over 30 candles, normalized by ATR.
        sample = closes[-30:]
        x_mean = 14.5
        y_mean = sum(sample) / len(sample)
        denominator = sum((i - x_mean) ** 2 for i in range(30))
        slope = sum((i - x_mean) * (value - y_mean) for i, value in enumerate(sample)) / denominator
        normalized_slope = (slope * 20) / atr_fast
        volatility_ratio = atr_fast / atr_slow

        if volatility_ratio >= 1.65:
            regime = "HIGH_VOLATILITY"
        elif volatility_ratio <= 0.72:
            regime = "COMPRESSION"
        elif efficiency <= 0.22 and abs(normalized_slope) < 0.12:
            regime = "RANGING"
        elif efficiency >= 0.30 and normalized_slope >= 0.18:
            regime = "TRENDING_UP"
        elif efficiency >= 0.30 and normalized_slope <= -0.18:
            regime = "TRENDING_DOWN"
        else:
            regime = "TRANSITION"

        if normalized_slope >= 0.18 and efficiency >= 0.25:
            bias = "BULLISH"
        elif normalized_slope <= -0.18 and efficiency >= 0.25:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        confidence = min(
            95,
            max(35, int(45 + efficiency * 35 + min(abs(normalized_slope), 1.5) * 10)),
        )
        if regime in ("RANGING", "COMPRESSION") and bias == "NEUTRAL":
            confidence = min(90, int(50 + (1 - efficiency) * 30))

        return {
            "active": True,
            "regime": regime,
            "directional_bias": bias,
            "confidence": confidence,
            "efficiency_ratio": round(efficiency, 4),
            "normalized_slope": round(normalized_slope, 4),
            "volatility_ratio": round(volatility_ratio, 4),
            "atr": round(atr_fast, 10),
            "timeframe": "4h",
            "source": "bybit_ohlcv",
            "reason": self._reason(regime, bias),
        }

    def _unknown(self, reason):
        return {
            "active": False,
            "regime": "UNKNOWN",
            "directional_bias": "NEUTRAL",
            "confidence": 0,
            "efficiency_ratio": None,
            "normalized_slope": None,
            "volatility_ratio": None,
            "atr": None,
            "timeframe": "4h",
            "source": "bybit_ohlcv",
            "reason": reason,
        }

    def _reason(self, regime, bias):
        labels = {
            "HIGH_VOLATILITY": "ATR expansion indicates unusually high volatility",
            "COMPRESSION": "ATR contraction indicates volatility compression",
            "RANGING": "Low directional efficiency indicates a range",
            "TRENDING_UP": "Directional efficiency and slope indicate an uptrend",
            "TRENDING_DOWN": "Directional efficiency and slope indicate a downtrend",
            "TRANSITION": "No sufficiently strong trend or range condition",
        }
        return labels.get(regime, "Regime unavailable")
