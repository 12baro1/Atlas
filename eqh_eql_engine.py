"""
eqh_eql_engine.py
Atlas Equal High / Equal Low Engine
"""


class EQHEQLEngine:
    """
    Detects Equal High / Equal Low liquidity pools across timeframes.
    """

    def __init__(self, tolerance=0.001, min_touches=2, min_separation=3):
        self.tolerance = tolerance
        self.min_touches = min_touches
        self.min_separation = min_separation

    def detect(self, timeframes, tolerance=None):
        tolerance = self.tolerance if tolerance is None else tolerance
        zones = []

        for timeframe, payload in timeframes.items():
            structure = payload.get("structure", [])
            candles = payload.get("candles", [])

            zones.extend(
                self._detect_timeframe(
                    timeframe=timeframe,
                    structure=structure,
                    candles=candles,
                    tolerance=tolerance
                )
            )

        zones.sort(
            key=lambda zone: (
                zone["swept"],
                -zone["score"],
                zone["timeframe"]
            )
        )

        confidence = self._confidence(zones)

        return {
            "valid": confidence >= 40,
            "confidence": confidence,
            "zones": zones,
            "summary": {
                "eqh": len([zone for zone in zones if zone["type"] == "EQH"]),
                "eql": len([zone for zone in zones if zone["type"] == "EQL"])
            }
        }

    def _detect_timeframe(self, timeframe, structure, candles, tolerance):
        highs = [item for item in structure if item.get("kind") == "HIGH" or item.get("type") == "HIGH"]
        lows = [item for item in structure if item.get("kind") == "LOW" or item.get("type") == "LOW"]

        zones = []
        zones.extend(self._cluster_swings(timeframe, highs, candles, "EQH", "BUY_SIDE", tolerance))
        zones.extend(self._cluster_swings(timeframe, lows, candles, "EQL", "SELL_SIDE", tolerance))

        return zones

    def _cluster_swings(self, timeframe, swings, candles, zone_type, liquidity, tolerance):
        zones = []
        clusters = []

        for swing in swings:
            price = swing.get("price")
            index = swing.get("index")

            if price is None or index is None:
                continue

            matched = False

            for cluster in clusters:
                if not self._within_tolerance(price, cluster["level"], tolerance):
                    continue

                if not self._is_separated(index, cluster["indices"]):
                    continue

                cluster["prices"].append(price)
                cluster["indices"].append(index)
                cluster["level"] = sum(cluster["prices"]) / len(cluster["prices"])
                matched = True
                break

            if not matched:
                clusters.append({
                    "level": price,
                    "prices": [price],
                    "indices": [index]
                })

        for cluster in clusters:
            touches = len(cluster["indices"])

            if touches < self.min_touches:
                continue

            swept = self._is_swept(candles, cluster, zone_type)
            score = self._score(cluster, touches, swept)

            if score < 35:
                continue

            zones.append({
                "type": zone_type,
                "timeframe": timeframe,
                "level": cluster["level"],
                "touches": touches,
                "indices": cluster["indices"],
                "tolerance": tolerance,
                "liquidity": liquidity,
                "swept": swept,
                "score": score
            })

        return zones

    def _within_tolerance(self, price, level, tolerance):
        if level == 0:
            return False

        return abs(price - level) / abs(level) <= tolerance

    def _is_separated(self, index, indices):
        return all(abs(index - existing) >= self.min_separation for existing in indices)

    def _is_swept(self, candles, cluster, zone_type):
        if not candles:
            return False

        last_index = max(cluster["indices"])
        level = cluster["level"]

        for candle in candles[last_index + 1:]:
            if zone_type == "EQH" and candle.high > level and candle.close < level:
                return True

            if zone_type == "EQL" and candle.low < level and candle.close > level:
                return True

        return False

    def _score(self, cluster, touches, swept):
        price_range = max(cluster["prices"]) - min(cluster["prices"])
        level = cluster["level"]
        tightness = 1 - min(1, price_range / level) if level else 0
        separation = max(cluster["indices"]) - min(cluster["indices"])

        score = 30
        score += min(30, touches * 10)
        score += int(tightness * 25)

        if separation >= self.min_separation * 3:
            score += 10

        if swept:
            score -= 20

        return max(0, min(100, score))

    def _confidence(self, zones):
        active_zones = [zone for zone in zones if not zone["swept"]]

        if not active_zones:
            return 0

        return min(100, max(zone["score"] for zone in active_zones))
