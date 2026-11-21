"""Independent volatility_breakout setup generator. Strategy logic lives in this package."""

from shared.analysis_services import (
    _value,
    _series,
    _atr,
    _bollinger,
    _candle_quality,
    _relative_volume,
    _current_price,
    _entry_reference,
)
from shared.market_structure_services import volatility_regime, breakout_acceptance
from strategies.candidate import _raw_candidate
from shared.specialist_evidence import evidence_for_strategy, attach_strategy_evidence


def generate(data):
    # Specialist outputs are optional context/provenance; native breakout rules
    # must remain capable of producing a setup when any or all are unavailable.
    specialist_evidence = evidence_for_strategy(data, "volatility_breakout")
    candles = data.get("1h") or []
    closes = _series(candles)
    atr = _atr(candles)
    if len(candles) < 45 or atr is None:
        return None
    # Require pre-breakout volatility compression; the current breakout bar
    # must close outside the prior range, not merely wick through it.
    bandwidths = []
    for end in range(max(20, len(closes) - 41), len(closes) - 1):
        band = _bollinger(closes[end - 20:end])
        if band:
            bandwidths.append((band[2] - band[0]) / max(band[1], 1e-12))
    prior_band = _bollinger(closes[-21:-1])
    volatility_evidence = volatility_regime(candles)
    breakout_evidence = breakout_acceptance(candles, 20)
    if not bandwidths or prior_band is None:
        return None
    prior_width = (prior_band[2] - prior_band[0]) / max(prior_band[1], 1e-12)
    compression_threshold = sorted(bandwidths)[max(0, int((len(bandwidths) - 1) * 0.50))]
    compressed = prior_width <= compression_threshold
    previous = candles[-21:-1]
    last = candles[-1]
    prior_highs = [_value(item, "high") for item in previous]
    prior_lows = [_value(item, "low") for item in previous]
    close = _value(last, "close")
    quality = _candle_quality(last)
    volume_ratio = _relative_volume(candles, 20)
    if close is None or quality is None or volume_ratio is None or any(item is None for item in prior_highs + prior_lows):
        return None
    entry = _current_price(data)
    if entry is None:
        return None
    upper_boundary, lower_boundary = max(prior_highs), min(prior_lows)
    direction = None
    if (close > upper_boundary and entry >= close and entry <= upper_boundary + atr
            and volume_ratio >= 1.15 and quality["direction"] == "BULLISH"
            and quality["body_ratio"] >= 0.40 and quality["close_location"] >= 0.65
            and quality["range"] >= 0.60 * atr):
        direction = "LONG"
    elif (close < lower_boundary and entry <= close and entry >= lower_boundary - atr
            and volume_ratio >= 1.30 and quality["direction"] == "BEARISH"
            and quality["body_ratio"] >= 0.50 and quality["close_location"] <= 0.35
            and quality["range"] >= 0.75 * atr):
        direction = "SHORT"
    else:
        return None
    boundary = upper_boundary if direction == "LONG" else lower_boundary
    breakout_distance = abs(entry - boundary) / atr
    strength = min(93.0, 61.0 + min(max(0.0, volume_ratio - 1.15) * 10.0, 15.0)
                   + min(quality["body_ratio"] * 10.0, 8.0)
                   + min(quality["range"] / atr * 5.0, 7.0))
    # Compression and acceptance increase confidence but are not standalone
    # mandatory conditions for a decisive 20-candle price breakout.
    strength = max(0.0, strength + (3.0 if compressed else -5.0))
    if breakout_evidence.get("state") != "ACCEPTED" or breakout_evidence.get("direction") != direction:
        strength = max(0.0, strength - 5.0)
    # _valid_plan in common filter computes structural stop; pass dummy stop (ignored)
    dummy_stop = entry - atr if direction == "LONG" else entry + atr
    plan = _raw_candidate(direction, entry, dummy_stop, atr, "volatility_breakout", strength, entry_reference=_entry_reference(data))
    if plan:
        plan["reasons"] = [
            f"1H 20-candle close breakout after volatility compression (bandwidth={prior_width:.4f})",
            f"Relative volume={volume_ratio:.2f}x median of prior 20 bars",
            f"Breakout candle body={quality['body_ratio']:.2f}; close-location={quality['close_location']:.2f}; range={quality['range'] / atr:.2f} ATR",
        ]
        plan["breakout_metrics"] = {"compression_bandwidth": round(prior_width, 6),
                                    "relative_volume": round(volume_ratio, 3),
                                    "candle_body_ratio": round(quality["body_ratio"], 3),
                                    "candle_range_atr": round(quality["range"] / atr, 3),
                                    "breakout_distance_atr": round(breakout_distance, 3),
                                    "acceptance": breakout_evidence, "volatility_regime": volatility_evidence}
    if plan:
        attach_strategy_evidence(plan, specialist_evidence)
    return plan

