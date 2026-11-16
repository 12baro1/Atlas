"""Public Kraken Futures liquidation-event stream.

Uses Kraken's public trade feed. Only exchange-labelled liquidation and
termination trades are emitted; ordinary fills are never inferred as liquidations.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque

KRAKEN_FUTURES_WS = "wss://futures.kraken.com/ws/v1"
KRAKEN_FUTURES_TICKERS = "https://futures.kraken.com/derivatives/api/v3/tickers"


def _canonical_base(value: str) -> str:
    base = str(value or "").split(":", 1)[0].upper()
    return "BTC" if base == "XBT" else base


class KrakenLiquidationStream:
    """One shared public WS connection collecting all linear perpetual events."""

    _shared = None
    _shared_lock = threading.RLock()

    @classmethod
    def shared(cls):
        with cls._shared_lock:
            if cls._shared is None:
                cls._shared = cls()
            return cls._shared

    def __init__(self, max_events: int = 20000):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._events = deque(maxlen=max_events)
        self._seen = set()
        self._product_bases = {}
        self._connected = False
        self._last_message_ms = None
        self._last_error = None

    @staticmethod
    def _load_products():
        import requests

        response = requests.get(KRAKEN_FUTURES_TICKERS, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload.get("result") != "success":
            raise RuntimeError("Kraken Futures ticker discovery failed")
        products = {}
        for row in payload.get("tickers", []):
            product_id = str(row.get("symbol") or "").upper()
            pair = str(row.get("pair") or "")
            # PF_ are linear perpetuals; exclude inverse, dated and options.
            if product_id.startswith("PF_") and row.get("tag") == "perpetual":
                base = _canonical_base(pair)
                if base:
                    products[product_id] = base
        if not products:
            raise RuntimeError("Kraken returned no linear perpetual products")
        return products

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        try:
            import websocket  # websocket-client
        except ImportError:
            self._last_error = "websocket-client is not installed"
            return False
        self._stop.clear()

        def worker():
            while not self._stop.is_set():
                ws = None
                try:
                    products = self._load_products()
                    with self._lock:
                        self._product_bases = products
                    ws = websocket.create_connection(
                        KRAKEN_FUTURES_WS, timeout=10, enable_multithread=True,
                        ping_interval=20, ping_timeout=10,
                    )
                    ws.send(json.dumps({
                        "event": "subscribe",
                        "feed": "trade",
                        "product_ids": sorted(products),
                    }))
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
                            message = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        self._consume(message)
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
                self._stop.wait(3.0)

        self._thread = threading.Thread(
            target=worker, name="atlas-kraken-liquidations", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _consume(self, message):
        feed = str(message.get("feed") or "")
        rows = []
        if feed == "trade":
            rows = [message]
        elif feed == "trade_snapshot":
            rows = message.get("trades") or []
        else:
            return
        with self._lock:
            for row in rows:
                event_type = str(row.get("type") or "").lower()
                if event_type not in {"liquidation", "termination"}:
                    continue
                product_id = str(row.get("product_id") or message.get("product_id") or "").upper()
                uid = str(row.get("uid") or "")
                if not product_id or not uid:
                    continue
                if product_id not in self._product_bases:
                    continue
                if uid in self._seen:
                    continue
                try:
                    stamp = int(row["time"])
                    price = float(row["price"])
                    quantity = float(row["qty"])
                    side = str(row.get("side") or "").lower()
                    if stamp <= 0 or price <= 0 or quantity <= 0 or side not in {"buy", "sell"}:
                        continue
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                event = {
                    "event_id": uid,
                    "exchange": "KRAKEN_FUTURES",
                    "symbol": self._product_bases[product_id],
                    "product_id": product_id,
                    "event_type": event_type,
                    "side": side.upper(),
                    "timestamp_ms": stamp,
                    "price": price,
                    "quantity": quantity,
                    "notional": price * quantity,
                    "source": "KRAKEN_FUTURES_PUBLIC_TRADE_WS",
                }
                self._events.append(event)
                self._seen.add(uid)
                self._last_message_ms = stamp
            # Bound the deduplication set to the retained event window.
            retained = {event["event_id"] for event in self._events}
            self._seen.intersection_update(retained)

    def snapshot(self, symbol: str, now_ms: int | None = None, max_age_ms: int = 120000):
        base = _canonical_base(str(symbol).split("/", 1)[0])
        now = int(now_ms or time.time() * 1000)
        with self._lock:
            events = [
                dict(event) for event in self._events
                if event["symbol"] == base
                and 0 <= now - event["timestamp_ms"] <= max_age_ms
            ]
            connected = self._connected
            last_message = self._last_message_ms
            error = self._last_error
            products = sum(1 for item in self._product_bases.values() if item == base)
        return {
            "events": events,
            "source": "KRAKEN_FUTURES_PUBLIC_TRADE_WS" if connected and products else "UNAVAILABLE",
            "connected": connected,
            "last_message_timestamp_ms": last_message,
            "last_error": error,
            "matched_products": products,
            "observed_at_ms": now,
        }
