"""Gate.io public Futures liquidations and trade-flow WebSocket collector."""
from __future__ import annotations

import json
import math
import threading
import time
from collections import deque


GATE_WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"


class GatePublicStream:
    _instances = {}
    _instances_lock = threading.RLock()

    @classmethod
    def for_symbol(cls, symbol):
        key = str(symbol)
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(key)
            return cls._instances[key]

    def __init__(self, symbol, max_events=20000):
        self.symbol = str(symbol)
        self.contract = self.symbol.split(":")[0].replace("/", "_").upper()
        self.base = self.contract.split("_")[0]
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._trades = deque(maxlen=max_events)
        self._liquidations = deque(maxlen=max_events)
        self._seen = set()
        self._connected = False
        self._last_message_ms = None
        self._last_error = None
        self._ticker = {}
        self._contract_size = 1.0

    def set_contract_size(self, value):
        try:
            size = float(value)
            if math.isfinite(size) and size > 0:
                self._contract_size = size
        except (TypeError, ValueError, OverflowError):
            return None

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        try:
            import websocket
        except ImportError:
            self._last_error = "websocket-client is not installed"
            return False
        self._stop.clear()

        def worker():
            while not self._stop.is_set():
                ws = None
                try:
                    ws = websocket.create_connection(GATE_WS_URL, timeout=10, enable_multithread=True)
                    subscriptions = (
                        ("futures.trades", [self.contract]),
                        ("futures.tickers", [self.contract]),
                        ("futures.public_liquidates", ["!all"]),
                    )
                    for channel, payload in subscriptions:
                        ws.send(json.dumps({"time": int(time.time()), "channel": channel,
                                            "event": "subscribe", "payload": payload}))
                    with self._lock:
                        self._connected = True
                        self._last_error = None
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv()
                        except websocket.WebSocketTimeoutException:
                            continue
                        if not raw:
                            continue
                        try:
                            self._consume(json.loads(raw))
                        except (TypeError, ValueError, UnicodeDecodeError):
                            continue
                except Exception as exc:
                    with self._lock:
                        self._last_error = str(exc)[:300]
                finally:
                    with self._lock:
                        self._connected = False
                    try:
                        if ws:
                            ws.close()
                    except Exception:
                        pass
                self._stop.wait(2.0)

        self._thread = threading.Thread(target=worker, name=f"atlas-gate-ws-{self.contract}", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _consume(self, message):
        channel = str(message.get("channel") or "")
        event = str(message.get("event") or "")
        if event == "subscribe":
            result = message.get("result") or {}
            if result.get("status") != "success" and message.get("error"):
                with self._lock:
                    self._last_error = str(message.get("error"))[:300]
            return
        if event != "update":
            return
        now_ms = int(message.get("time_ms") or int(message.get("time") or time.time()) * 1000)
        result = message.get("result")
        rows = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
        with self._lock:
            if channel == "futures.public_liquidates":
                for row in rows:
                    try:
                        contract = str(row.get("contract") or "").upper()
                        price = float(row["price"])
                        size = float(row["size"]) * self._contract_size
                        stamp = int(row.get("time") or now_ms)
                        if stamp < 10_000_000_000:
                            stamp *= 1000
                        if not contract or price <= 0 or size == 0 or not math.isfinite(price * size):
                            continue
                        event_id = f"gate:{contract}:{stamp}:{price}:{size}"
                        if event_id in self._seen:
                            continue
                        self._liquidations.append({
                            "event_id": event_id, "exchange": "GATEIO_FUTURES",
                            "symbol": contract.split("_")[0], "product_id": contract,
                            "event_type": "liquidation", "side": "SELL" if size < 0 else "BUY",
                            "timestamp_ms": stamp, "price": price, "quantity": abs(size),
                            "notional": price * abs(size), "source": "GATEIO_FUTURES_PUBLIC_LIQUIDATES_WS",
                        })
                        self._seen.add(event_id)
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            elif channel == "futures.trades":
                for row in rows:
                    try:
                        stamp = int(row.get("create_time_ms") or row.get("create_time") or now_ms)
                        if stamp < 10_000_000_000:
                            stamp *= 1000
                        size = float(row["size"])
                        price = float(row["price"])
                        if price <= 0 or size == 0:
                            continue
                        self._trades.append({
                            "timestamp_ms": stamp, "price": price, "size": abs(size),
                            "amount": abs(size), "side": "BUY" if size > 0 else "SELL",
                            "trade_id": str(row.get("id") or f"{stamp}:{price}:{size}"),
                        })
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            elif channel == "futures.tickers" and rows:
                self._ticker = dict(rows[0])
            self._last_message_ms = now_ms
            retained = {row["event_id"] for row in self._liquidations}
            self._seen.intersection_update(retained)

    def snapshot(self, now_ms=None, wait_ms=None):
        now = int(now_ms or time.time() * 1000)
        if wait_ms:
            deadline = time.monotonic() + min(float(wait_ms) / 1000, 15)
            while time.monotonic() < deadline:
                with self._lock:
                    if self._last_message_ms is not None:
                        break
                time.sleep(0.02)
            now = int(now_ms or time.time() * 1000)
        with self._lock:
            trades = [dict(row) for row in self._trades if 0 <= now - row["timestamp_ms"] <= 30000]
            liquidations = [dict(row) for row in self._liquidations
                            if row["symbol"] == self.base and 0 <= now - row["timestamp_ms"] <= 120000]
            connected = self._connected
            last_message = self._last_message_ms
            last_error = self._last_error
        buckets = {}
        for trade in self._trades:
            stamp = int(trade["timestamp_ms"])
            if stamp < now - 6 * 60 * 60 * 1000:
                continue
            bucket = stamp // 60000 * 60000
            item = buckets.setdefault(bucket, {"timestamp_ms": bucket, "buy_notional": 0.0, "sell_notional": 0.0})
            key = "buy_notional" if trade["side"] == "BUY" else "sell_notional"
            item[key] += trade["price"] * trade["size"]
        return {
            "source": "GATEIO_FUTURES_PUBLIC_WEBSOCKET", "connected": connected,
            "last_message_timestamp_ms": last_message,
            "orderbook": None, "orderbook_timestamp_ms": None, "orderbook_source": "REST",
            "recent_trades": trades,
            "recent_trades_timestamp_ms": max((x["timestamp_ms"] for x in trades), default=None),
            "recent_trades_source": "WEBSOCKET" if trades else "UNAVAILABLE",
            "trade_flow_history": [buckets[k] for k in sorted(buckets)],
            "trade_flow_history_source": "WEBSOCKET" if buckets else "UNAVAILABLE",
            "liquidation_events": liquidations,
            "liquidation_events_source": "GATEIO_FUTURES_PUBLIC_LIQUIDATES_WS" if connected else "UNAVAILABLE",
            "liquidation_events_timestamp_ms": max((x["timestamp_ms"] for x in liquidations), default=None),
            "liquidation_events_connected": connected,
            "liquidation_events_last_error": last_error,
            "liquidation_events_matched_products": 1,
        }
