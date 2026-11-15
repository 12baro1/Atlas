"""Optional Bybit V5 public WebSocket collector for linear perpetuals.

Uses websocket-client when installed. REST remains a fallback. The collector
records only exchange messages actually received; no synthetic history.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque


class BybitPublicStream:
    URL = "wss://stream.bybit.com/v5/public/linear"
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
        self.instrument = self.symbol.replace("/", "").replace(":USDT", "").replace(":", "")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._book = {"bids": {}, "asks": {}}
        self._book_timestamp_ms = None
        self._trades = deque(maxlen=max_events)
        self._liquidations = deque(maxlen=5000)
        self._connected = False
        self._last_message_ms = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        try:
            import websocket  # websocket-client; optional for mobile/minimal installs
        except ImportError:
            return False
        self._stop.clear()
        def worker():
            while not self._stop.is_set():
                ws = None
                try:
                    ws = websocket.create_connection(self.URL, timeout=10, enable_multithread=True)
                    topics = [f"orderbook.50.{self.instrument}", f"publicTrade.{self.instrument}", f"allLiquidation.{self.instrument}"]
                    ws.send(json.dumps({"op": "subscribe", "args": topics}))
                    with self._lock:
                        self._connected = True
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv()
                        except Exception:
                            break
                        if not raw:
                            continue
                        try:
                            self._consume(json.loads(raw))
                        except (TypeError, ValueError):
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
        self._thread = threading.Thread(target=worker, name=f"atlas-ws-{self.instrument}", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    @staticmethod
    def _levels(rows):
        output = {}
        for row in rows or []:
            try:
                price, size = float(row[0]), float(row[1])
                if price > 0 and size > 0:
                    output[price] = size
                elif price > 0 and size == 0:
                    output.pop(price, None)
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
        return output

    def _consume(self, message):
        topic = str(message.get("topic") or "")
        data = message.get("data")
        if not topic or data is None:
            return
        with self._lock:
            self._last_message_ms = int(time.time() * 1000)
            if topic.startswith("orderbook.") and isinstance(data, dict):
                kind = str(message.get("type") or "").lower()
                if kind == "snapshot":
                    self._book = {"bids": self._levels(data.get("b")), "asks": self._levels(data.get("a"))}
                else:
                    self._book.setdefault("bids", {}).update(self._levels(data.get("b")))
                    self._book.setdefault("asks", {}).update(self._levels(data.get("a")))
                    # Explicit zero-size updates delete levels.
                    for key, rows in (("bids", data.get("b")), ("asks", data.get("a"))):
                        for row in rows or []:
                            try:
                                if float(row[1]) == 0:
                                    self._book[key].pop(float(row[0]), None)
                            except (TypeError, ValueError, IndexError):
                                pass
                self._book_timestamp_ms = int(data.get("ts") or message.get("ts") or self._last_message_ms)
            elif topic.startswith("publicTrade."):
                for row in data if isinstance(data, list) else []:
                    try:
                        self._trades.append({"timestamp_ms": int(row.get("T") or message.get("ts")),
                                             "price": float(row["p"]), "size": float(row["v"]),
                                             "side": str(row["S"]).upper(), "trade_id": row.get("i")})
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            elif topic.startswith("allLiquidation."):
                for row in data if isinstance(data, list) else [data]:
                    try:
                        self._liquidations.append({"timestamp_ms": int(row.get("T") or message.get("ts")),
                                                   "price": float(row["p"]), "size": float(row["v"]),
                                                   "notional": float(row["p"]) * float(row["v"]),
                                                   "side": str(row["S"]).upper()})
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue

    def snapshot(self, now_ms=None):
        now = int(now_ms or time.time() * 1000)
        with self._lock:
            bids = sorted(self._book.get("bids", {}).items(), reverse=True)[:50]
            asks = sorted(self._book.get("asks", {}).items())[:50]
            trades = list(self._trades)
            liquidations = list(self._liquidations)
            book_ts, last_msg, connected = self._book_timestamp_ms, self._last_message_ms, self._connected
        book_age = now - int(book_ts) if book_ts else None
        fresh_book = bool(bids and asks and book_age is not None and 0 <= book_age <= 15000)
        fresh_trades = [x for x in trades if 0 <= now - x["timestamp_ms"] <= 30000]
        fresh_liquidations = [x for x in liquidations if 0 <= now - x["timestamp_ms"] <= 900000]
        return {"source": "BYBIT_V5_PUBLIC_WEBSOCKET", "connected": connected,
                "last_message_timestamp_ms": last_msg,
                "orderbook": {"bids": bids, "asks": asks, "timestamp": book_ts} if fresh_book else None,
                "orderbook_timestamp_ms": book_ts if fresh_book else None,
                "recent_trades": fresh_trades,
                "recent_trades_timestamp_ms": max((x["timestamp_ms"] for x in fresh_trades), default=None),
                "trade_flow_history": self._minute_batches(trades, now),
                "liquidation_events": fresh_liquidations}

    @staticmethod
    def _minute_batches(trades, now_ms):
        buckets = {}
        cutoff = now_ms - 6 * 60 * 60 * 1000
        for trade in trades:
            stamp = int(trade["timestamp_ms"])
            if stamp < cutoff:
                continue
            bucket = stamp // 60000 * 60000
            row = buckets.setdefault(bucket, {"timestamp_ms": bucket, "buy_notional": 0.0, "sell_notional": 0.0})
            key = "buy_notional" if trade["side"] == "BUY" else "sell_notional"
            row[key] += trade["price"] * trade["size"]
        return [buckets[key] for key in sorted(buckets)]
