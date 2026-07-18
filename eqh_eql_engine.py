"""
eqh_eql_engine.py
Atlas Equal High / Equal Low Engine
"""


class EQHEQLEngine:
    """Detects equal-high/equal-low liquidity pools across HTF and LTF data."""

    def __init__(self, tolerance=0.001, min_touches=2, min_separation=3, min_score=40):
        self.tolerance = tolerance
        self.min_touches = min_touches
        self.min_separation = min_separation
        self.min_score = min_score

    def detect(self, timeframes, tolerance=None):
        active_tolerance = self.tolerance if tolerance is None else tolerance
        zones = []

        for timeframe, payload in (timeframes or {}).items():
            zones.extend(
                self._detect_timeframe(
                    timeframe,
                    payload.get("structure", []),
                    payload.get("candles", []),
                    active_tolerance,
                )
            )

        zones.sort(key=lambda zone: (zone["swept"], -zone["score"], zone["timeframe"]))
        active_scores = [zone["score"] for zone in zones if not zone["swept"]]
        confidence = min(100, max(active_scores)) if active_scores else 0

        return {
            "valid": confidence >= self.min_score,
            "confidence": confidence,
            "zones": zones,
            "summary": self._summary(zones),
        }

    def _detect_timeframe(self, timeframe, structure, candles, tolerance):
        highs = self._swings(structure, "HIGH")
        lows = self._swings(structure, "LOW")
        return (
            self._cluster_swings(timeframe, highs, candles, "EQH", "BUY_SIDE", tolerance)
            + self._cluster_swings(timeframe, lows, candles, "EQL", "SELL_SIDE", tolerance)
        )

    def _swings(self, structure, swing_type):
        return [item for item in structure or [] if item.get("kind") == swing_type or item.get("type") == swing_type]

    def _cluster_swings(self, timeframe, swings, candles, zone_type, liquidity, tolerance):
        clusters = []
        for swing in swings:
            price = swing.get("price")
            index = swing.get("index")
            if price is None or index is None:
                continue
            cluster = self._matching_cluster(clusters, price, index, tolerance)
            if cluster is None:
                clusters.append({"level": price, "prices": [price], "indices": [index]})
                continue
            cluster["prices"].append(price)
            cluster["indices"].append(index)
            cluster["level"] = sum(cluster["prices"]) / len(cluster["prices"])

        zones = []
        for cluster in clusters:
            touches = len(cluster["indices"])
            if touches < self.min_touches:
                continue
            swept = self._is_swept(candles, cluster, zone_type)
            score = self._score(cluster, swept)
            if score < self.min_score:
                continue
            zones.append({
                "type": zone_type,
                "timeframe": timeframe,
                "level": cluster["level"],
                "touches": touches,
                "indices": list(cluster["indices"]),
                "tolerance": tolerance,
                "liquidity": liquidity,
                "swept": swept,
                "score": score,
            })
        return zones

    def _matching_cluster(self, clusters, price, index, tolerance):
        for cluster in clusters:
            if self._within_tolerance(price, cluster["level"], tolerance) and self._is_separated(index, cluster["indices"]):
                return cluster
        return None

    def _within_tolerance(self, price, level, tolerance):
        return bool(level) and abs(price - level) / abs(level) <= tolerance

    def _is_separated(self, index, indices):
        return all(abs(index - existing) >= self.min_separation for existing in indices)

    def _is_swept(self, candles, cluster, zone_type):
        level = cluster["level"]
        for candle in (candles or [])[max(cluster["indices"]) + 1:]:
            if zone_type == "EQH" and candle.high > level and candle.close < level:
                return True
            if zone_type == "EQL" and candle.low < level and candle.close > level:
                return True
        return False

    def _score(self, cluster, swept):
        level = abs(cluster["level"])
        price_range = max(cluster["prices"]) - min(cluster["prices"])
        tightness = 1 - min(1, price_range / level) if level else 0
        separation = max(cluster["indices"]) - min(cluster["indices"])
        score = 30 + min(30, len(cluster["indices"]) * 10) + int(tightness * 25)
        if separation >= self.min_separation * 3:
            score += 10
        if swept:
            score -= 20
        return max(0, min(100, score))

    def _summary(self, zones):
        return {
            "eqh": len([zone for zone in zones if zone["type"] == "EQH"]),
            "eql": len([zone for zone in zones if zone["type"] == "EQL"]),
            "active": len([zone for zone in zones if not zone["swept"]]),
        }
