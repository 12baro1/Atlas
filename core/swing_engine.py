"""Causal ATR swing detector retained for legacy/plugin consumers."""

from dataclasses import dataclass
import math


@dataclass
class Swing:
    index: int
    price: float
    kind: str


def _atr_at(candles, index, period=14):
    """ATR ending at index; never reads a candle after index."""
    first = max(1, index - period + 1)
    true_ranges = []
    for candle_index in range(first, index + 1):
        current = candles[candle_index]
        previous = candles[candle_index - 1]
        true_ranges.append(max(
            float(current.high) - float(current.low),
            abs(float(current.high) - float(previous.close)),
            abs(float(current.low) - float(previous.close)),
        ))
    if not true_ranges:
        return 0.0
    return sum(true_ranges) / len(true_ranges)


def detect(candles, multiplier=1.5):
    """Detect completed swings with an ATR threshold available at each bar."""
    if len(candles) < 30:
        return []
    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError, OverflowError):
        return []
    if not math.isfinite(multiplier) or multiplier <= 0:
        return []

    swings = []
    direction = None
    extreme = candles[0]
    extreme_index = 0

    for index, candle in enumerate(candles):
        if direction is None:
            if candle.close > extreme.close:
                direction = "UP"
            elif candle.close < extreme.close:
                direction = "DOWN"
            extreme = candle
            extreme_index = index
            continue

        threshold = _atr_at(candles, index) * multiplier
        if direction == "UP":
            if candle.high > extreme.high:
                extreme = candle
                extreme_index = index
            elif extreme.high - candle.low >= threshold:
                swings.append(Swing(extreme_index, extreme.high, "HIGH"))
                direction = "DOWN"
                extreme = candle
                extreme_index = index
        else:
            if candle.low < extreme.low:
                extreme = candle
                extreme_index = index
            elif candle.high - extreme.low >= threshold:
                swings.append(Swing(extreme_index, extreme.low, "LOW"))
                direction = "UP"
                extreme = candle
                extreme_index = index

    return swings
