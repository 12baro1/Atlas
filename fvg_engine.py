"""
fvg_engine.py
Atlas FVG Engine v4
"""

class FVGEngine:

    def detect(self, candles):

        gaps = []

        if len(candles) < 3:
            return gaps

        for i in range(2, len(candles)):

            left = candles[i - 2]
            mid = candles[i - 1]
            right = candles[i]

            # -------------------------
            # Bullish FVG
            # -------------------------

            if left.high < right.low:

                size = right.low - left.high

                strength = 0

                if size > 0:
                    strength += 50

                if mid.close > mid.open:
                    strength += 20

                if right.close > right.open:
                    strength += 20

                if right.close > mid.high:
                    strength += 10

                gaps.append({
                    "type": "BULLISH",
                    "from": left.high,
                    "to": right.low,
                    "size": size,
                    "strength": strength,
                    "filled": False,
                    "index": i
                })

            # -------------------------
            # Bearish FVG
            # -------------------------

            elif left.low > right.high:

                size = left.low - right.high

                strength = 0

                if size > 0:
                    strength += 50

                if mid.close < mid.open:
                    strength += 20

                if right.close < right.open:
                    strength += 20

                if right.close < mid.low:
                    strength += 10

                gaps.append({
                    "type": "BEARISH",
                    "from": right.high,
                    "to": left.low,
                    "size": size,
                    "strength": strength,
                    "filled": False,
                    "index": i
                })

        # -------------------------
        # Mitigation Check
        # -------------------------

        for gap in gaps:
            zone_low = min(float(gap["from"]), float(gap["to"]))
            zone_high = max(float(gap["from"]), float(gap["to"]))
            size = zone_high - zone_low
            deepest_price = None

            for candle in candles[gap["index"] + 1:]:
                # Track the deepest penetration. A wick touching the near edge
                # is mitigation, not a full fill of the entire imbalance.
                if gap["type"] == "BULLISH":
                    if candle.low <= zone_high:
                        deepest_price = candle.low if deepest_price is None else min(deepest_price, candle.low)
                else:
                    if candle.high >= zone_low:
                        deepest_price = candle.high if deepest_price is None else max(deepest_price, candle.high)

            if deepest_price is None or size <= 0:
                fill_ratio = 0.0
            elif gap["type"] == "BULLISH":
                fill_ratio = max(0.0, min(1.0, (zone_high - deepest_price) / size))
            else:
                fill_ratio = max(0.0, min(1.0, (deepest_price - zone_low) / size))

            gap["fill_ratio"] = round(fill_ratio, 4)
            gap["mitigation_pct"] = round(fill_ratio * 100, 2)
            gap["filled"] = fill_ratio >= 1.0

        return gaps

    def detect_inversion(self, candles):
        """Inverse FVG (IFVG) tespiti.

        Bir FVG'ye dönen fiyat fill edildikten sonra ters yönde itilirse,
        o bölge ters enstrüman olarak (resistance/support) işaretlenir.
        Dönüş: (candles) -> merkez mum seti üzerinden inversiyon bölgeleri.

        Algoritma:
        - 3'lü mum dizisinde bull/bear FVG'yi bul.
        - Sonraki mumlarda bölgeye temas edip kapanı ร fgap et (fill) -> inverted.
        - ''highest/lowest'' bir referans alanlarına göre sitilizasyon yerine
          ''from''/''to''/''type'' ve ''inverted'' bayrağı taşır.
        """
        if len(candles) < 4:
            return []

        inversions = []

        for i in range(2, len(candles)):
            left = candles[i - 2]
            mid = candles[i - 1]
            right = candles[i]

            if left.high < right.low:
                # bullish gap zone
                zone_from, zone_to = left.high, right.low
                direction = "BULLISH"
            elif left.low > right.high:
                # bearish gap zone
                zone_from, zone_to = right.high, left.low
                direction = "BEARISH"
            else:
                continue

            if zone_to <= zone_from:
                continue

            # gap fill edilmiş mi ve ardından ters itilmiş mi?
            fill_index = None

            for j in range(i + 1, len(candles)):
                c = candles[j]
                if c.high >= zone_from and c.low <= zone_to:
                    fill_index = j
                    break

            if fill_index is None:
                continue

            # İnversiyon = boşluk dolduktan SONRA fiyatın zıt yönde uzak kenarı
            # kapatması. Yalnızca doldurulmuş gap'i "inverted" işaretlemek
            # yanlıştır; trend yönünde devam eden bir dolduru inversiyon değildir.
            inverted = False
            if direction == "BULLISH":
                # Boşluğun altına kapanış → aşağı itilme
                for k in range(fill_index + 1, len(candles)):
                    if candles[k].close < zone_from:
                        inverted = True
                        break
            else:
                # Boşluğun üstüne kapanış → yukarı itilme
                for k in range(fill_index + 1, len(candles)):
                    if candles[k].close > zone_to:
                        inverted = True
                        break

            if inverted:
                inversions.append({
                    "type": direction,
                    "from": zone_from,
                    "to": zone_to,
                    "size": zone_to - zone_from,
                    "inverted": True,
                    "index": i,
                    "fill_index": fill_index,
                })

        return inversions
