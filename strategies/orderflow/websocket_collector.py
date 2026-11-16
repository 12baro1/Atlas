"""MEXC Futures public WebSocket collector for USDT perpetuals.

The collector only marks feeds available after valid exchange messages arrive.
MEXC's documented public futures channels provide depth, deals and ticker;
the public contract WebSocket does not document a liquidation-event channel,
so liquidation_events deliberately remain unavailable.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import threading
import time
from collections import deque

DEFAULT_FIRST_SNAPSHOT_WAIT_MS = 2500.0
MAX_FIRST_SNAPSHOT_WAIT_MS = 15000.0


def configured_first_snapshot_wait_ms():
    raw = os.getenv("ATLAS_WS_FIRST_SNAPSHOT_TIMEOUT_MS", str(DEFAULT_FIRST_SNAPSHOT_WAIT_MS))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_FIRST_SNAPSHOT_WAIT_MS
    if not math.isfinite(value) or value <= 0:
        return 0.0
    return min(value, MAX_FIRST_SNAPSHOT_WAIT_MS)


class MexcPublicStream:
    URL = "wss://contract.mexc.com/edge"
    _instances = {}
    _instances_lock = threading.RLock()

    @classmethod
    def for_symbol(cls, symbol):
        key = str(symbol)
        with cls._instances_lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = cls(key)
                cls._instances[key] = instance
            return instance

    def __init__(self, symbol, max_events=20000):
        self.symbol = str(symbol)
        self.instrument = self.symbol.split(":")[0].replace("/", "_").upper()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._book = {"bids": {}, "asks": {}}
        self._book_timestamp_ms = None
        self._trades = deque(maxlen=max_events)
        self._connected = False
        self._last_message_ms = None
        self._ticker = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        try:
            import websocket
        except ImportError:
            return False
        self._stop.clear()

        def worker():
            while not self._stop.is_set():
                ws = None
                try:
                    ws = websocket.create_connection(self.URL, timeout=10, enable_multithread=True)
                    for method, param in (
                        ("sub.depth.full", {"symbol": self.instrument, "limit": 20}),
                        ("sub.deal", {"symbol": self.instrument}),
                        ("sub.ticker", {"symbol": self.instrument}),
                    ):
                        ws.send(json.dumps({"method": method, "param": param, "gzip": False}))
                    with self._lock:
                        self._connected = True
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv()
                        except Exception:
                            try:
                                ws.send(json.dumps({"method": "ping"}))
                            except Exception:
                                break
                            continue
                        if not raw:
                            continue
                        try:
                            if isinstance(raw, bytes):
                                try:
                                    raw = gzip.decompress(raw).decode("utf-8")
                                except (OSError, UnicodeDecodeError):
                                    raw = raw.decode("utf-8")
                            self._consume(json.loads(raw))
                        except (TypeError, ValueError, UnicodeDecodeError):
                            continue
                except Exception:
                    pass
                finally:
                    with self._lock:
                        self._connected = False
                    try:
                        if ws:
                            ws.close()
                    except Exception:
                        pass
                self._stop.wait(2.0)

        self._thread = threading.Thread(
            target=worker, name=f"atlas-mexc-ws-{self.instrument}", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    @staticmethod
    def _book_levels(rows, quantity_index=2):
        output = {}
        for row in rows or []:
            try:
                price = float(row[0])
                quantity = float(row[quantity_index] if len(row) > quantity_index else row[1])
                if price > 0 and quantity > 0:
                    output[price] = quantity
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
        return output

    def _consume(self, message):
        channel = str(message.get("channel") or "")
        if not channel or channel.startswith(("rs.", "pong")):
            return
        data = message.get("data")
        if data is None:
            return
        stamp = int(message.get("ts") or time.time() * 1000)
        with self._lock:
            if channel in {"push.depth", "push.depth.full"} and isinstance(data, dict):
                # sub.depth.full supplies complete depth snapshots. Replace
                # both sides atomically rather than treating them as deltas.
                self._book = {
                    "bids": self._book_levels(data.get("bids")),
                    "asks": self._book_levels(data.get("asks")),
                }
                self._book_timestamp_ms = stamp
                self._last_message_ms = stamp
            elif channel == "push.deal":
                rows = data if isinstance(data, list) else [data]
                for row in rows:
                    try:
                        trade_stamp = int(row.get("t") or stamp)
                        side_code = int(row.get("T") or 0)
                        if side_code not in (1, 2):
                            continue
                        self._trades.append({
                            "timestamp_ms": trade_stamp,
                            "price": float(row["p"]),
                            "size": float(row["v"]),
                            "amount": float(row["v"]),
                            "side": "BUY" if side_code == 1 else "SELL",
                            "trade_id": str(trade_stamp),
                        })
                        self._last_message_ms = trade_stamp
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            elif channel == "push.ticker" and isinstance(data, dict):
                self._ticker = dict(data)
                self._last_message_ms = stamp

    def _has_any_message(self):
        with self._lock:
            return self._last_message_ms is not None

    def _await_first_message(self, timeout_seconds):
        deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0.0))
        while time.monotonic() < deadline:
            if self._has_any_message():
                return True
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
        return self._has_any_message()

    def snapshot(self, now_ms=None, wait_ms=None):
        now = int(now_ms or time.time() * 1000)
        if wait_ms is None:
            wait_ms = configured_first_snapshot_wait_ms()
        if wait_ms and wait_ms > 0:
            self._await_first_message(float(wait_ms) / 1000.0)
            now = int(now_ms) if now_ms is not None else int(time.time() * 1000)
        with self._lock:
            bids = sorted(self._book["bids"].items(), reverse=True)[:50]
            asks = sorted(self._book["asks"].items())[:50]
            trades = list(self._trades)
            book_ts = self._book_timestamp_ms
            last_msg = self._last_message_ms
            connected = self._connected
        book_age = now - int(book_ts) if book_ts else None
        fresh_book = bool(bids and asks and book_age is not None and 0 <= book_age <= 15000)
        fresh_trades = [row for row in trades if 0 <= now - row["timestamp_ms"] <= 30000]
        return {
            "source": "MEXC_FUTURES_PUBLIC_WEBSOCKET",
            "connected": connected,
            "last_message_timestamp_ms": last_msg,
            "orderbook": {
                "bids": bids, "asks": asks, "timestamp": book_ts,
            } if fresh_book else None,
            "orderbook_timestamp_ms": book_ts if fresh_book else None,
            "orderbook_source": "WEBSOCKET" if fresh_book else "UNAVAILABLE",
            "recent_trades": fresh_trades,
            "recent_trades_timestamp_ms": max(
                (row["timestamp_ms"] for row in fresh_trades), default=None
            ),
            "recent_trades_source": "WEBSOCKET" if fresh_trades else "UNAVAILABLE",
            "trade_flow_history": self._minute_batches(trades, now),
            "trade_flow_history_source": "WEBSOCKET" if trades else "UNAVAILABLE",
            # No public MEXC futures liquidation-event channel is documented.
            "liquidation_events": [],
            "liquidation_events_source": "UNAVAILABLE",
        }

    @staticmethod
    def _minute_batches(trades, now_ms):
        buckets = {}
        cutoff = now_ms - 6 * 60 * 60 * 1000
        for trade in trades:
            stamp = int(trade["timestamp_ms"])
            if stamp < cutoff:
                continue
            bucket = stamp // 60000 * 60000
            row = buckets.setdefault(
                bucket, {"timestamp_ms": bucket, "buy_notional": 0.0, "sell_notional": 0.0}
            )
            key = "buy_notional" if trade["side"] == "BUY" else "sell_notional"
            row[key] += trade["price"] * trade["size"]
        return [buckets[key] for key in sorted(buckets)]
