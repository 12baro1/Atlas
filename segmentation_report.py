"""Trade segmentation and deterministic JSON/CSV backtest reports."""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path


DIMENSIONS = ("entry_type", "regime", "volatility", "poi_source", "market_phase", "tp_behavior", "direction")


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def volatility_label(ratio):
    value = _number(ratio)
    if value is None:
        return "UNKNOWN"
    if value <= 0.72:
        return "COMPRESSION"
    if value >= 1.65:
        return "EXPANSION"
    return "NORMAL"


def classify_tp_behavior(trade):
    levels = trade.get("_levels", trade.get("levels", [])) or []
    try:
        hits = {int(level) for level in levels}
    except (TypeError, ValueError):
        hits = set()
    reason = str(trade.get("exit_reason") or trade.get("close_reason") or "").upper()
    result = str(trade.get("result") or "").upper()
    if 1 in hits:
        if result == "LOSS" or "STOP" in reason:
            return "TP1_THEN_STOP"
        return "TP3_HIT" if 3 in hits else "TP2_HIT" if 2 in hits else "TP1_HIT"
    if "STOP" in reason or "STOP_LOSS" in reason or result == "LOSS":
        return "FULL_STOP"
    if result == "WIN" and ("TARGET" in reason or "TP" in reason):
        return "TP1_HIT"
    return "UNRESOLVED" if result in ("", "OPEN", "PENDING") else "NO_TP"


def trade_dimensions(trade):
    regime = trade.get("regime", trade.get("market_regime"))
    poi = trade.get("poi_source", trade.get("poi_type"))
    phase = trade.get("market_phase")
    return {
        "entry_type": str(trade.get("entry_type") or "UNKNOWN").upper(),
        "regime": str(regime or "UNKNOWN").upper(),
        "volatility": volatility_label(trade.get("volatility_ratio", trade.get("volatility_value")))
            if not isinstance(trade.get("volatility"), str) else trade["volatility"].upper(),
        "poi_source": str(poi or "UNKNOWN").upper(),
        "market_phase": str(phase or "UNKNOWN").upper(),
        "tp_behavior": classify_tp_behavior(trade),
        "direction": str(trade.get("direction", trade.get("side")) or "UNKNOWN").upper(),
    }


def trade_metrics(trades):
    closed = [trade for trade in trades if str(trade.get("result") or "").upper() not in ("OPEN", "PENDING")]
    net_values = [_number(t.get("net_rr", t.get("pnl_rr"))) for t in closed]
    net_values = [v for v in net_values if v is not None]
    gross_values = [_number(t.get("gross_rr")) for t in closed]
    gross_values = [v for v in gross_values if v is not None]
    wins = [v for v in net_values if v > 0]
    losses = [v for v in net_values if v < 0]
    gross_wins = [v for v in gross_values if v > 0]
    gross_losses = [v for v in gross_values if v < 0]
    total = len(closed)
    gross_pf = sum(gross_wins) / abs(sum(gross_losses)) if gross_losses else (sum(gross_wins) if gross_wins else None)
    net_pf = sum(wins) / abs(sum(losses)) if losses else (sum(wins) if wins else None)
    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(len(wins) / total * 100, 2) if total else 0.0,
        "net_rr": round(sum(net_values), 4) if net_values else 0.0,
        "gross_rr": round(sum(gross_values), 4) if gross_values else None,
        "expectancy": round(sum(net_values) / total, 4) if total else 0.0,
        "gross_expectancy": round(sum(gross_values) / len(gross_values), 4) if gross_values else None,
        "profit_factor": round(net_pf, 4) if net_pf is not None else 0.0,
        "gross_profit_factor": round(gross_pf, 4) if gross_pf is not None else None,
        "low_sample": total < 30,
    }


def segment_breakdown(trades):
    groups = {dimension: defaultdict(list) for dimension in DIMENSIONS}
    for trade in trades:
        dimensions = trade_dimensions(trade)
        for dimension, value in dimensions.items():
            groups[dimension][value].append(trade)
    return {
        dimension: {key: trade_metrics(items) for key, items in sorted(values.items())}
        for dimension, values in groups.items()
    }


def build_report_payload(symbol_reports, combined_report, source="unknown", metadata=None):
    symbols = {}
    for symbol, report in sorted((symbol_reports or {}).items()):
        trades = list((report or {}).get("trades") or [])
        symbols[str(symbol)] = {
            "summary": trade_metrics(trades),
            "segments": segment_breakdown(trades),
        }
    combined_trades = list((combined_report or {}).get("trades") or [])
    return {
        "schema_version": 1,
        "source": str(source),
        "metadata": dict(metadata or {}),
        "sample_base": "realized_closed_trades",
        "symbols": symbols,
        "combined": {
            "summary": trade_metrics(combined_trades),
            "segments": segment_breakdown(combined_trades),
        },
    }


def flatten_report_rows(payload):
    rows = []
    for symbol, report in (payload.get("symbols") or {}).items():
        rows.append({"symbol": symbol, "dimension": "summary", "segment": "ALL", **report["summary"]})
        for dimension, segments in (report.get("segments") or {}).items():
            for segment, metrics in segments.items():
                rows.append({"symbol": symbol, "dimension": dimension, "segment": segment, **metrics})
    combined = payload.get("combined") or {}
    rows.append({"symbol": "COMBINED", "dimension": "summary", "segment": "ALL", **combined.get("summary", {})})
    for dimension, segments in (combined.get("segments") or {}).items():
        for segment, metrics in segments.items():
            rows.append({"symbol": "COMBINED", "dimension": dimension, "segment": segment, **metrics})
    return rows


def _atomic_write(path, writer):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_json_report(path, payload):
    def write(handle):
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    _atomic_write(path, write)


def write_csv_report(path, rows):
    rows = list(rows or [])
    fields = list(dict.fromkeys(key for row in rows for key in row))
    if not fields:
        fields = ["symbol", "dimension", "segment"]
    def write(handle):
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    _atomic_write(path, write)
