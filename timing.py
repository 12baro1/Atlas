"""Shared look-ahead-safe higher-timeframe candle boundaries."""

TF_PERIOD_MS = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
}


def closed_htf_candles(candles, reference_time_ms, timeframe=None):
    """Return only fully closed candles, in chronological order.

    Filtering every row (rather than breaking at the first future row) makes
    this safe when exchange/cache input is not already sorted.
    """
    if not candles:
        return []
    try:
        reference_ms = int(reference_time_ms)
    except (TypeError, ValueError, OverflowError):
        return []

    period_ms = TF_PERIOD_MS.get(str(timeframe).lower(), 0) if timeframe else 0
    closed = []
    for candle in candles:
        try:
            candle_time = int(candle.time)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if candle_time > reference_ms:
            continue
        if period_ms > 0 and candle_time + period_ms > reference_ms:
            continue
        closed.append((candle_time, candle))

    closed.sort(key=lambda item: item[0])
    return [candle for _, candle in closed]
