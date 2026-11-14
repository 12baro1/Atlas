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


def _coverage_status(records, start_ms, end_ms, interval_ms):
    records = sorted(records or [], key=lambda row: int(row.get("timestamp") or 0))
    if not records:
        return "UNAVAILABLE", 0.0
    start_ms = int(start_ms)
    end_ms = int(end_ms)
    interval_ms = max(1, int(interval_ms))
    expected = max(1, int(math.ceil(max(0, end_ms - start_ms) / interval_ms)))
    coverage_pct = min(100.0, len(records) / expected * 100.0)
    first_ms = int(records[0]["timestamp"])
    last_ms = int(records[-1]["timestamp"])
    endpoints_covered = first_ms <= start_ms + interval_ms and last_ms >= end_ms - interval_ms
    return ("HISTORICAL" if coverage_pct >= 90.0 and endpoints_covered else "PARTIAL"), round(coverage_pct, 2)


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
            status, coverage = _coverage_status(
                result["open_interest_records"], start_ms, end_ms, 60 * 60 * 1000
            )
            result["derivatives_data_quality"]["open_interest"] = status
            result["derivatives_data_quality"]["open_interest_coverage_pct"] = coverage
        except Exception as exc:
            result["derivatives_data_quality"]["open_interest"] = (
                f"UNAVAILABLE:{type(exc).__name__}"
            )
    else:
        result["derivatives_data_quality"]["open_interest"] = "UNSUPPORTED"
        result["derivatives_data_quality"]["open_interest_coverage_pct"] = 0.0

    funding_fetch = getattr(exchange, "fetch_funding_rate_history", None)
    if callable(funding_fetch):
        try:
            raw = _paginate(funding_fetch, symbol, start_ms, end_ms)
            result["funding_records"] = _normalise(
                raw, ("fundingRate",), start_ms, end_ms
            )
            status, coverage = _coverage_status(
                result["funding_records"], start_ms, end_ms, 8 * 60 * 60 * 1000
            )
            result["derivatives_data_quality"]["funding"] = status
            result["derivatives_data_quality"]["funding_coverage_pct"] = coverage
        except Exception as exc:
            result["derivatives_data_quality"]["funding"] = (
                f"UNAVAILABLE:{type(exc).__name__}"
            )
    else:
        result["derivatives_data_quality"]["funding"] = "UNSUPPORTED"
        result["derivatives_data_quality"]["funding_coverage_pct"] = 0.0
    return result
