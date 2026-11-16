"""Gate.io public Futures liquidations and trade-flow WebSocket collector."""
from __future__ import annotations

import json
import math
import threading
import time
from decimal import Decimal
from collections import deque


GATE_WS_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"


class GatePublicStream:
    _instances = {}
    _instances_lock = threading.RLock()
    _liquidation_owner = None
    _liquidation_lock = threading.RLock()
    _shared_liquidations = deque(maxlen=50000)
    _shared_liquidation_ids = set()

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
        self._book_bids = {}
        self._book_asks = {}
        self._book_update_id = None
        self._book_timestamp_ms = None
        self._book_updates = deque(maxlen=5000)
        self._book_synced = False
        self._open_interest = deque(maxlen=2000)

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

        with self._liquidation_lock:
            if self.__class__._liquidation_owner is None:
                self.__class__._liquidation_owner = self
            owns_liquidations = self.__class__._liquidation_owner is self

        def worker():
            while not self._stop.is_set():
                ws = None
                try:
                    ws = websocket.create_connection(GATE_WS_URL, timeout=10, enable_multithread=True,
                                                       header=["X-Gate-Size-Decimal: 1"])
                    subscriptions = [
                        ("futures.trades", [self.contract]),
                        ("futures.tickers", [self.contract]),
                        ("futures.order_book_update", [self.contract, "100ms", "50"]),
                        ("futures.contract_stats", [self.contract, "1m"]),
                    ]
                    if owns_liquidations:
                        subscriptions.append(("futures.public_liquidates", ["!all"]))
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
        with self.__class__._liquidation_lock:
            if self.__class__._liquidation_owner is self:
                self.__class__._liquidation_owner = None

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
                # One !all feed is shared; scale only after filtering to this symbol.
                with self.__class__._liquidation_lock:
                    for row in rows:
                        try:
                            contract = str(row.get("contract") or "").upper()
                            price = float(row["price"])
                            raw_size = float(row["size"])
                            stamp = int(row.get("time") or now_ms)
                            if stamp < 10_000_000_000:
                                stamp *= 1000
                            if not contract or price <= 0 or raw_size == 0 or not math.isfinite(price * raw_size):
                                continue
                            event_id = f"gate:{contract}:{stamp}:{price}:{raw_size}"
                            if event_id in self.__class__._shared_liquidation_ids:
                                continue
                            self.__class__._shared_liquidations.append({
                                "event_id": event_id, "contract": contract, "raw_size": raw_size,
                                "price": price, "timestamp_ms": stamp,
                            })
                            self.__class__._shared_liquidation_ids.add(event_id)
                        except (KeyError, TypeError, ValueError, OverflowError):
                            continue
                    retained = {row["event_id"] for row in self.__class__._shared_liquidations}
                    self.__class__._shared_liquidation_ids.intersection_update(retained)
            elif channel == "futures.trades":
                for row in rows:
                    try:
                        stamp = int(row.get("create_time_ms") or row.get("create_time") or now_ms)
                        if stamp < 10_000_000_000:
                            stamp *= 1000
                        raw_size = float(row["size"])
                        price = float(row["price"])
                        if price <= 0 or raw_size == 0:
                            continue
                        # Gate futures trade size is in contracts; normalize to
                        # base-asset quantity exactly once, like REST trades.
                        size = float(Decimal(str(abs(raw_size))) * Decimal(str(self._contract_size)))
                        if not math.isfinite(size) or size <= 0:
                            continue
                        self._trades.append({
                            "timestamp_ms": stamp, "price": price, "size": size,
                            "amount": size, "raw_contract_size": abs(raw_size),
                            "side": "BUY" if raw_size > 0 else "SELL",
                            "trade_id": str(row.get("id") or f"{stamp}:{price}:{raw_size}"),
                        })
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            elif channel == "futures.order_book_update":
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    try:
                        update = {"first": int(row["U"]), "last": int(row["u"]),
                                  "timestamp_ms": int(row.get("t") or now_ms),
                                  "bids": row.get("b") or [], "asks": row.get("a") or []}
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
                    if update["first"] > 0 and update["last"] >= update["first"]:
                        self._book_updates.append(update)
                        self._apply_book_update(update)
            elif channel == "futures.contract_stats":
                for row in rows:
                    try:
                        stamp = int(row.get("time") or 0)
                        if stamp < 10_000_000_000:
                            stamp *= 1000
                        raw_value = row.get("open_interest_usd")
                        if raw_value is None:
                            raw_value = row.get("open_interest")
                        value = float(raw_value)
                        if stamp > 0 and math.isfinite(value) and value > 0:
                            self._open_interest.append({"timestamp": stamp, "openInterestValue": value})
                    except (TypeError, ValueError, OverflowError):
                        continue
            elif channel == "futures.tickers" and rows:
                self._ticker = dict(rows[0])
            self._last_message_ms = now_ms
            retained = {row["event_id"] for row in self._liquidations}
            self._seen.intersection_update(retained)

    def _apply_book_update(self, update):
        if not self._book_synced:
            return
        expected = int(self._book_update_id) + 1
        if update["last"] < expected:
            return
        if not update["first"] <= expected <= update["last"]:
            self._book_synced = False
            self._book_bids.clear()
            self._book_asks.clear()
            self._book_update_id = None
            return
        for side, changes in ((self._book_bids, update["bids"]), (self._book_asks, update["asks"])):
            for level in changes:
                try:
                    price = float(level.get("p") if isinstance(level, dict) else level[0])
                    raw_size = float(level.get("s") if isinstance(level, dict) else level[1])
                    if price <= 0 or not math.isfinite(price) or not math.isfinite(raw_size):
                        continue
                    if raw_size == 0:
                        side.pop(price, None)
                    else:
                        size = float(Decimal(str(abs(raw_size))) * Decimal(str(self._contract_size)))
                        if size > 0 and math.isfinite(size):
                            side[price] = size
                except (TypeError, ValueError, IndexError, OverflowError):
                    continue
        self._book_update_id = update["last"]
        self._book_timestamp_ms = update["timestamp_ms"]

    def set_orderbook_snapshot(self, snapshot):
        """Seed L2 from a REST nonce and replay only contiguous buffered updates."""
        try:
            nonce = int(snapshot.get("nonce"))
            bids = {float(p): float(q) for p, q in snapshot.get("bids", []) if float(p) > 0 and float(q) > 0}
            asks = {float(p): float(q) for p, q in snapshot.get("asks", []) if float(p) > 0 and float(q) > 0}
            if nonce <= 0 or not bids or not asks:
                return False
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False
        with self._lock:
            self._book_bids, self._book_asks = bids, asks
            self._book_update_id = nonce
            self._book_timestamp_ms = int(snapshot.get("timestamp") or time.time() * 1000)
            self._book_synced = True
            for update in list(self._book_updates):
                if update["last"] <= self._book_update_id:
                    continue
                self._apply_book_update(update)
                if not self._book_synced:
                    return False
            return self._book_synced

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
            with self.__class__._liquidation_lock:
                liquidations = []
                for raw in self.__class__._shared_liquidations:
                    if raw["contract"].split("_")[0] != self.base:
                        continue
                    if not 0 <= now - raw["timestamp_ms"] <= 120000:
                        continue
                    size = float(Decimal(str(raw["raw_size"])) * Decimal(str(self._contract_size)))
                    liquidations.append({
                        "event_id": raw["event_id"], "exchange": "GATEIO_FUTURES",
                        "symbol": self.base, "product_id": raw["contract"],
                        "event_type": "liquidation",
                        "side": "SELL" if size < 0 else "BUY",
                        "order_side": "SELL" if size < 0 else "BUY",
                        "position_side": "LONG" if size < 0 else "SHORT",
                        "side_semantics": "GATE_ORDER_SIDE_AND_LIQUIDATED_POSITION",
                        "timestamp_ms": raw["timestamp_ms"], "price": raw["price"],
                        "quantity": abs(size), "notional": raw["price"] * abs(size),
                        "source": "GATEIO_FUTURES_PUBLIC_LIQUIDATES_WS",
                    })
            orderbook = None
            if self._book_synced and self._book_bids and self._book_asks:
                orderbook = {
                    "symbol": self.symbol,
                    "bids": [[p, q] for p, q in sorted(self._book_bids.items(), reverse=True)[:50]],
                    "asks": [[p, q] for p, q in sorted(self._book_asks.items())[:50]],
                    "timestamp": self._book_timestamp_ms, "nonce": self._book_update_id, "datetime": None,
                }
            open_interest = [dict(row) for row in self._open_interest if 0 <= now - row["timestamp"] <= 2 * 60 * 60 * 1000]
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
            "orderbook": orderbook, "orderbook_timestamp_ms": orderbook.get("timestamp") if orderbook else None,
            "orderbook_source": "WEBSOCKET" if orderbook else "REST",
            "recent_trades": trades,
            "recent_trades_timestamp_ms": max((x["timestamp_ms"] for x in trades), default=None),
            "recent_trades_source": "WEBSOCKET" if trades else "UNAVAILABLE",
            "trade_flow_history": [buckets[k] for k in sorted(buckets)],
            "trade_flow_history_source": "WEBSOCKET" if buckets else "UNAVAILABLE",
            "open_interest": open_interest,
            "open_interest_source": "GATEIO_FUTURES_PUBLIC_WEBSOCKET" if len(open_interest) >= 2 else "UNAVAILABLE",
            "liquidation_events": liquidations,
            "liquidation_events_source": "GATEIO_FUTURES_PUBLIC_LIQUIDATES_WS" if liquidations else "UNAVAILABLE",
            "liquidation_events_timestamp_ms": max((x["timestamp_ms"] for x in liquidations), default=None),
            "liquidation_events_connected": connected,
            "liquidation_events_last_error": last_error,
            "liquidation_events_matched_products": 1,
        }
