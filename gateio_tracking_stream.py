"""Multiplexed Gate.io public trades for the virtual trade tracker."""
import json
import logging
import threading
import time
from collections import deque
from math import isfinite

from gateio_futures import GateFuturesExchange, trade_timestamp_ms
from strategies.orderflow.gateio_public_stream import GATE_WS_URL
from tracking_history import EvidenceMissing, TradeGroup

logger = logging.getLogger("atlas.tracking_stream")


class GateTrackingStream:
    """Use socket history only across an observed, uninterrupted subscription."""

    def __init__(self):
        self._wanted = set()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="AtlasGateTracking", daemon=True)
        self._trades = {}
        self._covered_from = {}
        self._released_until = {}

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)

    def follow(self, symbols):
        with self._lock:
            self._wanted = {GateFuturesExchange.market_id(symbol) for symbol in symbols}

    def _clear(self, contract):
        self._trades.pop(contract, None)
        self._covered_from.pop(contract, None)
        self._released_until.pop(contract, None)

    def _consume(self, envelope, subscribed):
        if envelope.get("channel") != "futures.trades":
            return
        if envelope.get("error"):
            raise ConnectionError("Gate rejected a trade subscription")
        if envelope.get("event") != "update":
            return
        trades = envelope["result"]
        if isinstance(trades, dict):
            trades = [trades]
        if not isinstance(trades, list):
            raise ValueError("Invalid Gate trade array")
        with self._lock:
            for row in trades:
                contract = row["contract"]
                if contract not in subscribed or contract not in self._wanted:
                    continue
                if row.get("is_internal") is True:
                    continue
                stamp = trade_timestamp_ms(row["create_time_ms"])
                trade_id = int(row["id"])
                price, size = float(row["price"]), abs(float(row["size"]))
                if stamp <= 0 or not all(isfinite(value) and value > 0 for value in (price, size)):
                    raise ValueError("Invalid Gate trade")
                trades = self._trades.setdefault(contract, deque(maxlen=20000))
                if trades and (stamp, trade_id, price, size) == trades[-1]:
                    continue
                if stamp < self._released_until.get(contract, 0) or (trades and stamp < trades[-1][0]):
                    raise ValueError("Gate trade arrived out of order")
                # Start on a whole second strictly after the opening trade.
                # REST can bridge to that second without splitting any tick group.
                self._covered_from.setdefault(contract, (stamp // 1000 + 1) * 1000)
                if len(trades) == trades.maxlen:
                    self._covered_from[contract] = max(self._covered_from[contract], (trades[0][0] // 1000 + 1) * 1000)
                trades.append((stamp, trade_id, price, size))

    def trade_range(self, symbol, start, end, fallback=None):
        contract = GateFuturesExchange.market_id(symbol)
        with self._lock:
            coverage = self._covered_from.get(contract, end)
            socket_start = max(start, min(coverage, end))
            socket_end = min(end, self._trades[contract][-1][0]) if contract in self._trades else end
            if fallback is not None and socket_end <= socket_start:
                socket_start = end
            ticks = {}
            ids = set()
            if socket_start < socket_end:
                for stamp, trade_id, price, size in reversed(self._trades[contract]):
                    if stamp < socket_start:
                        break
                    if stamp >= socket_end or trade_id in ids:
                        continue
                    ids.add(trade_id)
                    group = ticks.setdefault(stamp, TradeGroup(stamp))
                    group.prices.add(price)
                    group.volume += size
                self._released_until[contract] = max(socket_end, self._released_until.get(contract, 0))

        older = []
        if start < socket_start:
            if fallback is None or socket_start % 1000:
                raise EvidenceMissing("Anlık işlem akışında geçmiş aralık eksik")
            older = fallback(symbol, start, socket_start)
        return older + [ticks[stamp] for stamp in sorted(ticks)]

    def _run(self):
        import websocket

        while not self._stop.is_set():
            with self._lock:
                wanted = self._wanted.copy()
            if not wanted:
                self._stop.wait(1)
                continue
            socket = None
            try:
                socket = websocket.create_connection(GATE_WS_URL, timeout=4,
                                                      header=["X-Gate-Size-Decimal: 1"])
                socket.settimeout(1)
                subscribed = set()
                while not self._stop.is_set():
                    with self._lock:
                        wanted = self._wanted.copy()
                        for contract in subscribed - wanted:
                            self._clear(contract)
                    if not wanted:
                        break
                    for action, contracts in (("unsubscribe", subscribed - wanted), ("subscribe", wanted - subscribed)):
                        if contracts:
                            socket.send(json.dumps({"time": int(time.time()), "channel": "futures.trades",
                                                    "event": action, "payload": sorted(contracts)}))
                    subscribed = wanted
                    try:
                        raw = socket.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw:
                        raise ConnectionError("Gate trade socket closed")
                    self._consume(json.loads(raw), subscribed)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                logger.warning("Gate trade stream reconnecting (%s)", type(exc).__name__)
            finally:
                with self._lock:
                    self._trades.clear()
                    self._covered_from.clear()
                    self._released_until.clear()
                if socket is not None:
                    try:
                        socket.close(timeout=0)
                    except (OSError, websocket.WebSocketException):
                        pass
            self._stop.wait(2)
