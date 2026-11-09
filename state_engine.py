"""Persistent state and incremental-analysis helpers for Atlas."""

import json
import os
import threading
import time
from pathlib import Path


class StateEngine:
    """Stores compact per-symbol analysis state in JSON so restarts can resume quickly."""

    VERSION = 1

    def __init__(self, path="atlas_state.json"):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.state = {"version": self.VERSION, "symbols": {}, "open_positions": {}, "updated_at": None}
        self.load()

    def load(self):
        if not self.path.exists():
            return self.state
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                symbols = payload.get("symbols")
                positions = payload.get("open_positions")
                if isinstance(symbols, dict):
                    self.state["symbols"] = {
                        str(symbol): value
                        for symbol, value in symbols.items()
                        if isinstance(value, dict)
                    }
                if isinstance(positions, dict):
                    self.state["open_positions"] = {
                        str(key): value
                        for key, value in positions.items()
                        if isinstance(value, dict)
                    }
                updated_at = payload.get("updated_at")
                if isinstance(updated_at, (int, float)) and not isinstance(updated_at, bool):
                    self.state["updated_at"] = updated_at
        except (OSError, json.JSONDecodeError):
            # Keep running with empty state; next successful save repairs the file.
            pass
        return self.state

    def save(self):
        with self._lock:
            self.state["updated_at"] = int(time.time() * 1000)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_name(f"{self.path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(self.state, handle, ensure_ascii=False, separators=(",", ":"), default=self._json_default)
            try:
                os.replace(tmp_path, self.path)
            finally:
                tmp_path.unlink(missing_ok=True)
            return self.state

    def get_symbol_state(self, symbol):
        return self.state.setdefault("symbols", {}).get(symbol)

    def has_new_entry_candle(self, symbol, candles):
        if not candles:
            return True
        symbol_state = self.get_symbol_state(symbol) or {}
        last_time = self._last_candle_time(symbol_state)
        try:
            current_time = int(candles[-1].time)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return True
        return last_time is None or current_time > last_time

    def new_candles_since_last(self, symbol, candles):
        symbol_state = self.get_symbol_state(symbol) or {}
        last_time = self._last_candle_time(symbol_state)
        if last_time is None:
            return candles
        result = []
        for candle in candles:
            try:
                candle_time = int(candle.time)
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if candle_time > last_time:
                result.append(candle)
        return result

    @staticmethod
    def _last_candle_time(symbol_state):
        last_candle = symbol_state.get("last_candle") if isinstance(symbol_state, dict) else None
        if not isinstance(last_candle, dict):
            return None
        try:
            return int(last_candle.get("time"))
        except (TypeError, ValueError, OverflowError):
            return None

    def restore_cached_result(self, symbol):
        symbol_state = self.get_symbol_state(symbol) or {}
        cached = symbol_state.get("last_result")
        if not isinstance(cached, dict) or not cached:
            return None
        cached = dict(cached)
        cached["incremental"] = {"cache_hit": True, "reason": "no_new_candle"}
        return cached

    def update_analysis_state(self, symbol, data, result):
        analysis = (result or {}).get("analysis", {})
        entry_candles = data.get("15m") or []
        last_candle = self._compact_candle(entry_candles[-1]) if entry_candles else None
        self.state.setdefault("symbols", {})[symbol] = {
            "symbol": symbol,
            "last_candle": last_candle,
            "last_result": self._compact_result(result),
            "updated_at": int(time.time() * 1000),
        }
        self.save()

    def sync_open_positions(self, positions):
        self.state["open_positions"] = {
            f"{pos.get('symbol')}:{pos.get('side')}:{pos.get('entry')}": dict(pos)
            for pos in positions or []
            if pos.get("status") == "OPEN"
        }
        self.save()

    def load_open_positions(self):
        positions = self.state.get("open_positions", {})
        if not isinstance(positions, dict):
            return []
        return [dict(position) for position in positions.values() if isinstance(position, dict)]

    def _compact_result(self, result):
        if not isinstance(result, dict):
            return None
        return {
            "signal": result.get("signal"),
            "risk": result.get("risk"),
            "rr": result.get("rr"),
            "dynamic_tp": result.get("dynamic_tp"),
            "decision": result.get("decision"),
            "analysis": self._compact_analysis(result.get("analysis") or {}),
        }

    def _compact_analysis(self, analysis):
        return {
            "structure": self._compact_list(analysis.get("structure", [])),
            "bos": self._compact_list(analysis.get("bos", [])),
            "choch": self._compact_list(analysis.get("choch", [])),
            "fvg": self._compact_list(analysis.get("fvg", [])),
            "orderblocks": self._compact_list(analysis.get("orderblocks", [])),
            "liquidity": self._compact_list(analysis.get("liquidity", [])),
            "entry": analysis.get("entry"),
            "confluence": analysis.get("confluence"),
            "market_phase": analysis.get("market_phase"),
            "setup_quality": analysis.get("setup_quality"),
        }

    def _compact_list(self, values, limit=200):
        if not isinstance(values, list):
            return []
        return [self._json_default(item) for item in values[-limit:]]

    def _compact_candle(self, candle):
        return {
            "time": int(candle.time),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": float(candle.volume),
        }

    def _json_default(self, value):
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return value
