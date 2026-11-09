"""Confirmed swing-pivot extraction used by Atlas' market-structure pipeline."""

from core.pivot import Pivot


class MarketStructureEngine:
    def __init__(self):
        self.pivots = []
        self.pivot_left = 5
        self.pivot_right = 5

    def find_pivots(self, candles, left=5, right=5):
        """Find pivots only after the complete right-side window is present."""
        try:
            left = int(left)
            right = int(right)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("left and right pivot windows must be positive integers") from exc
        if left < 1 or right < 1:
            raise ValueError("left and right pivot windows must be >= 1")

        self.pivots = []
        self.pivot_left = left
        self.pivot_right = right
        if not candles:
            return self.pivots

        for index in range(left, len(candles) - right):
            candle = candles[index]
            high = float(candle.high)
            low = float(candle.low)
            is_high = True
            is_low = True

            for other_index in range(index - left, index + right + 1):
                if other_index == index:
                    continue
                other = candles[other_index]
                if float(other.high) >= high:
                    is_high = False
                if float(other.low) <= low:
                    is_low = False
                if not is_high and not is_low:
                    break

            confirmation_index = index + right
            if is_high:
                self.pivots.append(Pivot(
                    index=index,
                    price=high,
                    kind="HIGH",
                    confirmation_index=confirmation_index,
                ))
            if is_low:
                self.pivots.append(Pivot(
                    index=index,
                    price=low,
                    kind="LOW",
                    confirmation_index=confirmation_index,
                ))

        self.pivots.sort(key=lambda pivot: (pivot.index, pivot.kind))
        return self.pivots

    def calculate_strength(self, candles):
        """Score only candles in the pivot's bounded left/right context."""
        candle_count = len(candles)
        for pivot in self.pivots:
            left_index = max(0, pivot.index - self.pivot_left)
            confirmation_index = getattr(pivot, "confirmation_index", None)
            if confirmation_index is None:
                confirmation_index = pivot.index + self.pivot_right
            right_index = min(candle_count, int(confirmation_index) + 1)

            strength = 0
            for index in range(left_index, right_index):
                if index == pivot.index:
                    continue
                candle = candles[index]
                if pivot.kind == "HIGH" and float(candle.high) < pivot.price:
                    strength += 1
                elif pivot.kind == "LOW" and float(candle.low) > pivot.price:
                    strength += 1
            pivot.strength = strength
        return self.pivots

    def merge_pivots(self, max_distance=6):
        try:
            max_distance = int(max_distance)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("max_distance must be a non-negative integer") from exc
        if max_distance < 0:
            raise ValueError("max_distance must be >= 0")
        if len(self.pivots) < 2:
            return self.pivots

        merged = []
        current = self.pivots[0]
        for candidate in self.pivots[1:]:
            if candidate.kind == current.kind and candidate.index - current.index <= max_distance:
                if candidate.kind == "HIGH":
                    if candidate.price > current.price:
                        current = candidate
                elif candidate.price < current.price:
                    current = candidate
            else:
                merged.append(current)
                current = candidate
        merged.append(current)
        self.pivots = merged
        return self.pivots

    def filter_noise(self, min_strength=3):
        """Discard weak pivots; default threshold is reachable with 5x5 windows."""
        try:
            min_strength = float(min_strength)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("min_strength must be a finite non-negative number") from exc
        if min_strength < 0:
            raise ValueError("min_strength must be >= 0")

        filtered = []
        for pivot in self.pivots:
            if float(pivot.strength) >= min_strength:
                pivot.confirmed = True
                filtered.append(pivot)
        self.pivots = filtered
        return self.pivots

    def validate_sequence(self):
        """Keep alternating highs/lows, retaining the more extreme same-kind pivot."""
        if len(self.pivots) < 2:
            return self.pivots

        result = [self.pivots[0]]
        for pivot in self.pivots[1:]:
            last = result[-1]
            if pivot.kind != last.kind:
                result.append(pivot)
            elif pivot.kind == "HIGH" and pivot.price > last.price:
                result[-1] = pivot
            elif pivot.kind == "LOW" and pivot.price < last.price:
                result[-1] = pivot
        self.pivots = result
        return self.pivots
