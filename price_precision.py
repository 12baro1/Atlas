"""Exchange tick-size normalization and directional price snapping."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import math


def normalize_tick_size(value):
    try:
        tick = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return tick if math.isfinite(tick) and tick > 0 else None


def snap_price_to_tick(price, tick_size, direction="nearest"):
    """Snap a positive price to an exchange tick using decimal arithmetic."""
    tick = normalize_tick_size(tick_size)
    try:
        value = Decimal(str(price))
    except (InvalidOperation, TypeError, ValueError):
        return float(price)
    if tick is None or not value.is_finite() or value <= 0:
        return float(value)
    step = Decimal(str(tick))
    rounding = {
        "floor": ROUND_FLOOR,
        "ceiling": ROUND_CEILING,
        "nearest": ROUND_HALF_UP,
    }.get(str(direction).lower(), ROUND_HALF_UP)
    units = (value / step).to_integral_value(rounding=rounding)
    return float(units * step)
