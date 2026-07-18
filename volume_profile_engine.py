"""
volume_profile_engine.py
Atlas Volume Profile Engine v1
"""

from core.analysis_utils import clamp


class VolumeProfileEngine:
    """Hacim dağılımından kritik işlem bölgelerini üretir."""

    SUPPORTED_TIMEFRAMES = ("15m", "1h", "4h", "1d")

    def detect(self, candles, bins=36):
        """Tek zaman dilimi için volume profile analizi döndürür."""
        if not candles or len(candles) < 10:
            return self._empty()

        low = min(c.low for c in candles)
        high = max(c.high for c in candles)

        if high <= low:
            return self._empty()

        step = (high - low) / max(bins, 1)
        histogram = [0.0 for _ in range(bins)]

        for candle in candles:
            rng = max(candle.high - candle.low, 1e-9)
            start = int((candle.low - low) / step)
            end = int((candle.high - low) / step)
            start = max(0, min(bins - 1, start))
            end = max(0, min(bins - 1, end))

            span = max(end - start + 1, 1)
            body = abs(candle.close - candle.open)
            body_ratio = min(1.0, body / rng)
            distributed_volume = (candle.volume * (0.55 + (0.45 * body_ratio))) / span

            for index in range(start, end + 1):
                histogram[index] += distributed_volume

        total_volume = sum(histogram)
        if total_volume <= 0:
            return self._empty()

        poc_index = max(range(bins), key=lambda idx: histogram[idx])
        poc = low + ((poc_index + 0.5) * step)

        vah_index, val_index = self._value_area(histogram, poc_index, 0.70)
        vah = low + ((vah_index + 1) * step)
        val = low + (val_index * step)

        hvn_indexes = self._top_nodes(histogram, count=3)
        lvn_indexes = self._bottom_nodes(histogram, count=3)

        hvn = [low + ((idx + 0.5) * step) for idx in hvn_indexes]
        lvn = [low + ((idx + 0.5) * step) for idx in lvn_indexes]

        current_price = candles[-1].close
        profile_state = self._profile_state(current_price, vah, val, poc)
        confidence = self._confidence(histogram, poc_index, vah_index, val_index, current_price, vah, val)
        bias = self._direction_bias(profile_state)

        return {
            "active": True,
            "poc": round(poc, 8),
            "vah": round(vah, 8),
            "val": round(val, 8),
            "hvn": [round(price, 8) for price in hvn],
            "lvn": [round(price, 8) for price in lvn],
            "current_price": round(current_price, 8),
            "state": profile_state,
            "direction": bias,
            "confidence": confidence,
            "bias_strength": self._bias_strength(current_price, poc, vah, val),
            "value_area_position": self._value_area_position(current_price, vah, val),
            "total_volume": round(total_volume, 4),
        }

    def detect_multi(self, timeframe_payload, bins=36):
        """Çoklu zaman diliminde volume profile üretir."""
        by_timeframe = {}
        active_profiles = []

        for timeframe in self.SUPPORTED_TIMEFRAMES:
            candles = timeframe_payload.get(timeframe)
            if not candles:
                continue

            profile = self.detect(candles, bins=bins)
            by_timeframe[timeframe] = profile

            if profile.get("active"):
                active_profiles.append((timeframe, profile))

        best = None
        if active_profiles:
            best_tf, best_profile = max(active_profiles, key=lambda item: item[1].get("confidence", 0))
            best = {
                "timeframe": best_tf,
                **best_profile,
            }

        direction = "NONE"
        if best:
            if best["direction"] == "BULLISH":
                direction = "BULLISH"
            elif best["direction"] == "BEARISH":
                direction = "BEARISH"

        return {
            "active": best is not None,
            "direction": direction,
            "confidence": best["confidence"] if best else 0,
            "best": best,
            "timeframes": by_timeframe,
        }

    def _value_area(self, histogram, poc_index, target_ratio):
        total = sum(histogram)
        covered = histogram[poc_index]

        left = poc_index
        right = poc_index

        while total > 0 and (covered / total) < target_ratio:
            left_volume = histogram[left - 1] if left > 0 else -1
            right_volume = histogram[right + 1] if right < len(histogram) - 1 else -1

            if right_volume >= left_volume and right < len(histogram) - 1:
                right += 1
                covered += histogram[right]
            elif left > 0:
                left -= 1
                covered += histogram[left]
            else:
                break

        return right, left

    def _top_nodes(self, histogram, count=3):
        indexed = list(enumerate(histogram))
        indexed.sort(key=lambda item: item[1], reverse=True)
        return [item[0] for item in indexed[:count]]

    def _bottom_nodes(self, histogram, count=3):
        indexed = list(enumerate(histogram))
        indexed.sort(key=lambda item: item[1])
        return [item[0] for item in indexed[:count]]

    def _profile_state(self, current_price, vah, val, poc):
        if current_price >= vah:
            return "PREMIUM"
        if current_price <= val:
            return "DISCOUNT"

        midpoint = (vah + val) / 2
        poc_distance = abs(current_price - poc) / max(vah - val, 1e-9)

        if poc_distance <= 0.10:
            return "POC_NEAR"

        if current_price >= midpoint:
            return "VALUE_HIGH"
        if current_price <= midpoint:
            return "VALUE_LOW"

        if current_price >= poc:
            return "ABOVE_POC"
        return "BELOW_POC"

    def _confidence(self, histogram, poc_index, vah_index, val_index, current_price, vah, val):
        total = max(sum(histogram), 1e-9)
        poc_share = histogram[poc_index] / total

        in_value = val <= current_price <= vah
        value_bonus = 12 if in_value else 4

        spread = max(vah - val, 1e-9)
        concentration = min(40, int((poc_share * 100)))
        distribution_quality = min(30, int((1 / spread) * 2))
        proximity_bonus = max(0, int(15 - (abs(current_price - ((vah + val) / 2)) / spread) * 20))

        score = 28 + concentration + distribution_quality + value_bonus + proximity_bonus
        return int(clamp(score))

    def _direction_bias(self, state):
        if state in ["DISCOUNT", "VALUE_LOW", "BELOW_POC", "POC_NEAR"]:
            return "BULLISH"
        if state in ["PREMIUM", "VALUE_HIGH", "ABOVE_POC"]:
            return "BEARISH"
        return "NONE"

    def _bias_strength(self, current_price, poc, vah, val):
        spread = max(vah - val, 1e-9)
        distance = abs(current_price - poc) / spread
        return int(clamp(100 - (distance * 100), 0, 100))

    def _value_area_position(self, current_price, vah, val):
        if current_price >= vah:
            return "ABOVE_VALUE"
        if current_price <= val:
            return "BELOW_VALUE"

        midpoint = (vah + val) / 2
        if current_price >= midpoint:
            return "UPPER_VALUE"
        return "LOWER_VALUE"

    def _empty(self):
        return {
            "active": False,
            "poc": None,
            "vah": None,
            "val": None,
            "hvn": [],
            "lvn": [],
            "current_price": None,
            "state": "NONE",
            "direction": "NONE",
            "confidence": 0,
            "bias_strength": 0,
            "value_area_position": "NONE",
            "total_volume": 0,
        }
