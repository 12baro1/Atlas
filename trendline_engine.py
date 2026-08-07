"""
trendline_engine.py
Atlas Trendline Liquidity & Sweep Engine

Trendline liquidity: Sway/suport çizgileri diyagonal likidite havuzlarıdır.
Trendline sweep: Fiyat trendline'ı wick ile kırıp kapatırsa (stop-run) sweep gerçekleşir.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Trendline:
    slope: float
    intercept: float
    direction: str  # "SUPPORT" | "RESISTANCE"
    start_index: int
    end_index: int
    touches: int = 0
    touch_indices: List[int] = field(default_factory=list)
    price_at_end: float = 0.0
    broken: bool = False
    break_index: Optional[int] = None

    def price_at(self, index: int) -> float:
        return self.intercept + self.slope * index


@dataclass
class TrendlineSweep:
    trendline: Optional[Trendline] = None
    direction: Optional[str] = None  # "BUY_SIDE" | "SELL_SIDE"
    sweep_index: Optional[int] = None
    close_index: Optional[int] = None
    wick_pierce: float = 0.0
    recovery: float = 0.0
    active: bool = False
    reason: str = ""


class TrendlineEngine:
    """Swing noktalarından trendline çıkarır, likidite ve sweep tespiti yapar."""

    def __init__(self, min_touches=2, max_lookback=60, tolerance_pct=0.002):
        self.min_touches = min_touches
        self.max_lookback = max_lookback
        self.tolerance_pct = tolerance_pct

    def detect(
        self,
        structure: List[dict],
        candles: List,
        direction: str = "SUPPORT",
    ) -> List[Trendline]:
        """Swing noktalarından trendline(lar) üretir.

        SUPPORT: yükselen dip noktalarından (sweep sonrası yukarı yön)
        RESISTANCE: alçalan tepe noktalarından.
        """
        if len(candles) < 5:
            return []

        points = self._collect_swing_points(structure, candles, direction)
        if len(points) < self.min_touches:
            return []

        # En iyi iki/üç noktaya doğruyu oturt, tolerans dahilindeki tüm temasları say
        best = self._best_fit(points, candles)
        return best if best else []

    def _collect_swing_points(self, structure, candles, direction):
        if direction == "SUPPORT":
            return [
                {"index": item["index"], "price": item["price"]}
                for item in structure
                if item.get("kind") == "LOW"
            ]
        return [
            {"index": item["index"], "price": item["price"]}
            for item in structure
            if item.get("kind") == "HIGH"
        ]

    def _best_fit(self, points, candles):
        """En çok temasa sahip, tolerans dahilindeki doğruyu bulur."""
        # Referans index aralığı
        candidates = []
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                p1, p2 = points[i], points[j]
                if p2["index"] == p1["index"]:
                    continue
                slope = (p2["price"] - p1["price"]) / (p2["index"] - p1["index"])
                intercept = p1["price"] - slope * p1["index"]
                # Tolerans: ortalama fiyatın belirli bir yüzdesi
                tolerance = p1["price"] * self.tolerance_pct
                touch_indices = []
                for k in range(len(points)):
                    p = points[k]
                    expected = intercept + slope * p["index"]
                    if abs(expected - p["price"]) <= max(tolerance, self.tolerance_pct * abs(expected)):
                        touch_indices.append(p["index"])
                if len(touch_indices) >= self.min_touches:
                    candidates.append(
                        {
                            "slope": slope,
                            "intercept": intercept,
                            "touch_indices": sorted(touch_indices),
                            "touches": len(touch_indices),
                            "start_index": touch_indices[0],
                            "end_index": touch_indices[-1],
                        }
                    )

        if not candidates:
            return []

        # En çok temasa sahip, ardından en güncel olanı seç
        candidates.sort(key=lambda c: (c["touches"], c["end_index"]), reverse=True)
        chosen = candidates[0]

        trendline = Trendline(
            slope=chosen["slope"],
            intercept=chosen["intercept"],
            direction="RESISTANCE" if chosen["slope"] < 0 else "SUPPORT",
            start_index=chosen["start_index"],
            end_index=chosen["end_index"],
            touches=chosen["touches"],
            touch_indices=chosen["touch_indices"],
            price_at_end=chosen["intercept"] + chosen["slope"] * chosen["end_index"],
        )

        # Kırılma tespiti
        self._check_break(trendline, candles)
        return [trendline]

    def _check_break(self, trendline: Trendline, candles):
        last_idx = len(candles) - 1
        if trendline.end_index >= last_idx:
            return
        for idx in range(trendline.end_index + 1, len(candles)):
            candle = candles[idx]
            trend_price = trendline.price_at(idx)
            if trendline.direction == "SUPPORT":
                if candle.low < trend_price:
                    trendline.broken = True
                    trendline.break_index = idx
                    break
            else:
                if candle.high > trend_price:
                    trendline.broken = True
                    trendline.break_index = idx
                    break

    def detect_liquidity(
        self,
        structure: List[dict],
        candles: List,
        current_price: float,
    ) -> List[dict]:
        """Trendline'ları diyagonal likidite olarak sunar."""
        payload = []
        for direction in ("SUPPORT", "RESISTANCE"):
            for tl in self.detect(structure, candles, direction):
                payload.append(
                    {
                        "type": "SELL_SIDE" if direction == "RESISTANCE" else "BUY_SIDE",
                        "kind": "TRENDLINE",
                        "direction": direction,
                        "slope": round(tl.slope, 8),
                        "intercept": round(tl.intercept, 8),
                        "touches": tl.touches,
                        "touch_indices": tl.touch_indices,
                        "start_index": tl.start_index,
                        "end_index": tl.end_index,
                        "price": round(tl.price_at_end, 8),
                        "broken": tl.broken,
                        "distance": round(abs(current_price - tl.price_at_end), 8),
                    }
                )
        return payload

    def detect_sweep(
        self,
        structure: List[dict],
        candles: List,
        current_index: Optional[int] = None,
    ) -> TrendlineSweep:
        """Trendline sweep: fiyat trendline'ı geçip (wick) geri kapanırsa sweep.

        SUPPORT çizgisi: aşağı wick kırıp yukarı kapanırsa sell-side sweep
        (fiyat dipteki stopları topladı -> LONG fırsatı).
        RESISTANCE çizgisi: yukarı wick kırıp aşağı kapanırsa buy-side sweep.
        """
        current_index = current_index if current_index is not None else len(candles) - 1
        if current_index < 1:
            return TrendlineSweep()

        current = candles[current_index]
        prev = candles[current_index - 1]

        for direction in ("SUPPORT", "RESISTANCE"):
            for tl in self.detect(structure, candles, direction):
                if tl.end_index >= current_index:
                    continue
                trend_price = tl.price_at(current_index)
                prev_trend_price = tl.price_at(current_index - 1)

                if direction == "SUPPORT":
                    pierced = current.low < trend_price and current.high > trend_price
                    closed_above = current.close > trend_price
                    prev_above = prev.close > prev_trend_price
                else:
                    pierced = current.high > trend_price and current.low < trend_price
                    closed_above = current.close < trend_price
                    prev_above = prev.close < prev_trend_price

                if pierced and closed_above and prev_above:
                    wick_pierce = abs(current.low - trend_price) if direction == "SUPPORT" else abs(current.high - trend_price)
                    return TrendlineSweep(
                        trendline=tl,
                        direction="SELL_SIDE" if direction == "SUPPORT" else "BUY_SIDE",
                        sweep_index=current_index,
                        close_index=current_index,
                        wick_pierce=round(wick_pierce, 8),
                        recovery=round(abs(current.close - trend_price), 8),
                        active=True,
                        reason=f"{direction} trendline swept at candle {current_index}",
                    )
        return TrendlineSweep()

    def serialize(self, sweep: TrendlineSweep) -> dict:
        return {
            "active": sweep.active,
            "direction": sweep.direction,
            "sweep_index": sweep.sweep_index,
            "close_index": sweep.close_index,
            "wick_pierce": sweep.wick_pierce,
            "recovery": sweep.recovery,
            "reason": sweep.reason,
            "trendline": (
                {
                    "direction": sweep.trendline.direction,
                    "slope": sweep.trendline.slope,
                    "intercept": sweep.trendline.intercept,
                    "touches": sweep.trendline.touches,
                    "touch_indices": sweep.trendline.touch_indices,
                    "start_index": sweep.trendline.start_index,
                    "end_index": sweep.trendline.end_index,
                    "price_at_end": sweep.trendline.price_at_end,
                    "broken": sweep.trendline.broken,
                }
                if sweep.trendline
                else None
            ),
        }
