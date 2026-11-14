"""Historical Bybit derivatives series for leak-free strategy replay.

Missing or unsupported endpoints return explicit empty series plus diagnostics;
the caller must never substitute current snapshots for historical values.
"""
from __future__ import annotations

import math

from data_engine import exchange


def _normalise(records, value_keys, start_ms, end_ms):
    output = []
    seen = set()
    for item in records or []:
        if not isinstance(item, dict):
            continue
        try:
            timestamp = int(item.get("timestamp") or 0)
            raw = next((item.get(key) for key in value_keys if item.get(key) is not None), None)
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if timestamp < start_ms or timestamp > end_ms or not math.isfinite(value):
            continue
        if timestamp <= 0 or timestamp in seen:
            continue
        seen.add(timestamp)
        output.append({"timestamp": timestamp, "value": value})
    return sorted(output, key=lambda row: row["timestamp"])


def _paginate(fetch, symbol, start_ms, end_ms, *, timeframe=None, limit=200):
    records = []
    cursor = int(start_ms)
    last_cursor = None
    for _ in range(30):
        kwargs = {"since": cursor, "limit": limit}
        if timeframe:
            kwargs["timeframe"] = timeframe
        batch = fetch(symbol, **kwargs) or []
        if not isinstance(batch, list) or not batch:
            break
        records.extend(item for item in batch if isinstance(item, dict))
        stamps = []
        for item in batch:
            try:
                stamp = int(item.get("timestamp") or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if stamp > 0:
                stamps.append(stamp)
        if not stamps:
            break
        newest = max(stamps)
        if newest >= end_ms or newest <= cursor or newest == last_cursor:
            break
        last_cursor = newest
        cursor = newest + 1
    return records


def load_historical_derivatives(symbol, start_ms, end_ms):
    """Fetch timestamped OI/funding history; no current-value fallback."""
    result = {
        "open_interest_records": [],
        "funding_records": [],
        "derivatives_data_quality": {},
    }
    oi_fetch = getattr(exchange, "fetch_open_interest_history", None)
    if callable(oi_fetch):
        try:
            raw = _paginate(oi_fetch, symbol, start_ms, end_ms, timeframe="1h")
            result["open_interest_records"] = _normalise(
                raw, ("openInterestValue", "openInterestAmount"), start_ms, end_ms
            )
            result["derivatives_data_quality"]["open_interest"] = (
                "HISTORICAL" if result["open_interest_records"] else "UNAVAILABLE"
            )
        except Exception as exc:
            result["derivatives_data_quality"]["open_interest"] = (
                f"UNAVAILABLE:{type(exc).__name__}"
            )
    else:
        result["derivatives_data_quality"]["open_interest"] = "UNSUPPORTED"

    funding_fetch = getattr(exchange, "fetch_funding_rate_history", None)
    if callable(funding_fetch):
        try:
            raw = _paginate(funding_fetch, symbol, start_ms, end_ms)
            result["funding_records"] = _normalise(
                raw, ("fundingRate",), start_ms, end_ms
            )
            result["derivatives_data_quality"]["funding"] = (
                "HISTORICAL" if result["funding_records"] else "UNAVAILABLE"
            )
        except Exception as exc:
            result["derivatives_data_quality"]["funding"] = (
                f"UNAVAILABLE:{type(exc).__name__}"
            )
    else:
        result["derivatives_data_quality"]["funding"] = "UNSUPPORTED"
    return result
