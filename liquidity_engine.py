"""
liquidity_engine.py
Atlas SMC Engine
"""

class LiquidityEngine:

    def detect(self, structure, tolerance=0.001):

        clusters = self._build_clusters(
            levels=structure,
            tolerance=tolerance,
            liquidity_kind="SWING",
        )

        return [cluster for cluster in clusters if cluster["touches"] >= 2]

    def detect_internal(self, candles, tolerance=0.0008):

        if len(candles) < 5:
            return []

        points = self._extract_internal_points(candles)
        clusters = self._build_clusters(
            levels=points,
            tolerance=tolerance,
            liquidity_kind="INTERNAL",
        )

        return [cluster for cluster in clusters if cluster["touches"] >= 2]

    def detect_layers(self, structure, candles, swing_tolerance=0.001, internal_tolerance=0.0008):

        swing = self.detect(structure, tolerance=swing_tolerance)
        internal = self.detect_internal(candles, tolerance=internal_tolerance)
        all_clusters = swing + internal

        return {
            "swing": swing,
            "internal": internal,
            "all": all_clusters,
            "bsl": [item for item in all_clusters if item["type"] == "BUY_SIDE"],
            "ssl": [item for item in all_clusters if item["type"] == "SELL_SIDE"],
            "eqh": [item for item in all_clusters if item["eq"] == "EQH"],
            "eql": [item for item in all_clusters if item["eq"] == "EQL"],
        }

    def _build_clusters(self, levels, tolerance, liquidity_kind):

        zones = []

        highs = []
        lows = []

        for item in levels:

            if item["kind"] == "HIGH":

                matched = False

                for level in highs:
                    if abs(level["price"] - item["price"]) / level["price"] <= tolerance:
                        level["touches"] += 1
                        matched = True
                        break

                if not matched:
                    highs.append({
                        "price": item["price"],
                        "touches": 1,
                        "type": "BUY_SIDE",
                        "eq": "EQH",
                        "liquidity_kind": liquidity_kind,
                    })

            else:

                matched = False

                for level in lows:
                    if abs(level["price"] - item["price"]) / level["price"] <= tolerance:
                        level["touches"] += 1
                        matched = True
                        break

                if not matched:
                    lows.append({
                        "price": item["price"],
                        "touches": 1,
                        "type": "SELL_SIDE",
                        "eq": "EQL",
                        "liquidity_kind": liquidity_kind,
                    })

        for level in highs + lows:
            zones.append(level)

        return zones

    def _extract_internal_points(self, candles):

        points = []

        for index in range(1, len(candles) - 1):
            left = candles[index - 1]
            center = candles[index]
            right = candles[index + 1]

            if center.high > left.high and center.high > right.high:
                points.append(
                    {
                        "kind": "HIGH",
                        "price": center.high,
                    }
                )

            if center.low < left.low and center.low < right.low:
                points.append(
                    {
                        "kind": "LOW",
                        "price": center.low,
                    }
                )

        return points
