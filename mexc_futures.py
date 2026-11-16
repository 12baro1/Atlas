"""Public MEXC USDT-perpetual market-data adapter.

This intentionally implements only the read-only subset consumed by Atlas.
It never signs requests or submits orders. MEXC reports many derivative quantities in contracts; the adapter converts
those quantities to base-asset units using each contract's contractSize and
normalizes symbols/timestamps into Atlas' existing market-data interface.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

import requests


BASE_URL = "https://contract.mexc.com"
_INTERVALS = {
    "1m": ("Min1", 60), "5m": ("Min5", 300), "15m": ("Min15", 900),
    "30m": ("Min30", 1800), "1h": ("Min60", 3600), "4h": ("Hour4", 14400),
    "8h": ("Hour8", 28800), "1d": ("Day1", 86400), "1w": ("Week1", 604800),
}


class MexcFuturesExchange:
    """Small CCXT-compatible read-only adapter for MEXC perpetual contracts."""

    id = "mexc"
    name = "MEXC Futures"

    def __init__(self, session=None, timeout=15):
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.markets = {}
        self.symbols = []
        self._last_ticker = {}
        self._oi_history = defaultdict(list)
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    @staticmethod
    def milliseconds():
        return int(time.time() * 1000)

    @staticmethod
    def parse_timeframe(timeframe):
        if timeframe not in _INTERVALS:
            raise ValueError(f"Unsupported MEXC timeframe: {timeframe}")
        return _INTERVALS[timeframe][1]

    @staticmethod
    def market_id(symbol):
        value = str(symbol or "").strip().upper()
        if "_" in value and "/" not in value:
            return value
        base_quote = value.split(":")[0].replace("/", "_")
        return base_quote

    @staticmethod
    def unified_symbol(contract):
        base = str(contract.get("baseCoin") or "").upper()
        quote = str(contract.get("quoteCoin") or "").upper()
        settle = str(contract.get("settleCoin") or quote).upper()
        return f"{base}/{quote}:{settle}"

    def _get(self, path, params=None):
        # Contract detail is limited to one request per five seconds; other
        # public market endpoints allow 20 requests per two-second window.
        with self._request_lock:
            delay = 0.105 - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
            response = self.session.get(
                BASE_URL + path, params=params or {}, timeout=self.timeout
            )
            self._last_request_at = time.monotonic()
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise RuntimeError(
                f"MEXC public API error for {path}: "
                f"{payload.get('code') if isinstance(payload, dict) else 'invalid_response'}"
            )
        return payload.get("data")

    def load_markets(self, reload=False, params=None):
        if self.markets and not reload:
            return self.markets
        rows = self._get("/api/v1/contract/detail") or []
        markets = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("state") != 0:
                continue
            if str(row.get("quoteCoin") or "").upper() != "USDT":
                continue
            if str(row.get("settleCoin") or "").upper() != "USDT":
                continue
            symbol = self.unified_symbol(row)
            markets[symbol] = {
                "id": row.get("symbol"), "symbol": symbol,
                "base": row.get("baseCoin"), "quote": row.get("quoteCoin"),
                "settle": row.get("settleCoin"), "active": True,
                "swap": True, "spot": False, "future": False,
                "contract": True, "linear": True, "inverse": False,
                "contractSize": float(row.get("contractSize") or 1),
                "precision": {
                    "price": row.get("priceScale"),
                    "amount": row.get("volScale"),
                },
                "limits": {
                    "amount": {"min": row.get("minVol"), "max": row.get("maxVol")},
                },
                "info": dict(row),
            }
        self.markets = markets
        self.symbols = sorted(markets)
        return self.markets

    def market(self, symbol):
        if not self.markets:
            self.load_markets()
        return self.markets[symbol]

    def contract_size(self, symbol):
        market = self.markets.get(symbol) if self.markets else None
        if market is None:
            market = self.market(symbol)
        return float((market or {}).get("contractSize") or 1.0)

    def fetch_ohlcv(self, symbol, timeframe="1m", since=None, limit=None, params=None):
        interval, seconds = _INTERVALS[timeframe]
        contract_size = self.contract_size(symbol)
        now = self.milliseconds()
        count = min(max(int(limit or 500), 1), 2000)
        end_s = now // 1000
        start_s = int(since // 1000) if since is not None else end_s - seconds * count
        if since is not None:
            end_s = min(end_s, start_s + seconds * count)
        data = self._get(
            f"/api/v1/contract/kline/{self.market_id(symbol)}",
            {"interval": interval, "start": start_s, "end": end_s},
        ) or {}
        times = data.get("time") or []
        rows = []
        for i, stamp in enumerate(times):
            try:
                rows.append([
                    int(stamp) * 1000,
                    float(data["open"][i]), float(data["high"][i]),
                    float(data["low"][i]), float(data["close"][i]),
                    float(data.get("vol", [0] * len(times))[i]) * contract_size,
                ])
            except (KeyError, IndexError, TypeError, ValueError, OverflowError):
                continue
        return sorted(rows, key=lambda row: row[0])[-count:]

    def fetch_order_book(self, symbol, limit=50, params=None):
        contract_size = self.contract_size(symbol)
        data = self._get(f"/api/v1/contract/depth/{self.market_id(symbol)}",
                         {"limit": min(max(int(limit or 50), 1), 50)}) or {}
        def levels(rows):
            output = []
            for row in rows or []:
                try:
                    price, amount = float(row[0]), float(row[1])
                    if price > 0 and amount > 0:
                        output.append([price, amount * contract_size])
                except (IndexError, TypeError, ValueError, OverflowError):
                    continue
            return output
        return {
            "symbol": symbol, "bids": levels(data.get("bids")),
            "asks": levels(data.get("asks")),
            "timestamp": int(data.get("timestamp") or self.milliseconds()),
            "nonce": data.get("version"), "datetime": None,
        }

    def fetch_trades(self, symbol, since=None, limit=100, params=None):
        contract_size = self.contract_size(symbol)
        rows = self._get(
            f"/api/v1/contract/deals/{self.market_id(symbol)}",
            {"limit": min(max(int(limit or 100), 1), 100)},
        ) or []
        output = []
        for row in rows:
            try:
                stamp = int(row["t"])
                if since is not None and stamp < int(since):
                    continue
                side = "buy" if int(row.get("T") or 0) == 1 else "sell"
                output.append({
                    "id": str(row.get("t", "")), "timestamp": stamp,
                    "datetime": None, "symbol": symbol, "type": None,
                    "side": side, "price": float(row["p"]),
                    "amount": float(row["v"]) * contract_size, "cost": None,
                    "info": dict(row),
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return sorted(output, key=lambda item: item["timestamp"])[-int(limit or 100):]

    def _normalize_ticker(self, symbol, data):
        data = data or {}
        contract_size = self.contract_size(symbol)
        ticker = {
            "symbol": symbol, "timestamp": int(data.get("timestamp") or self.milliseconds()),
            "datetime": None, "high": data.get("high24Price"),
            "low": data.get("lower24Price"), "bid": data.get("bid1"),
            "ask": data.get("ask1"), "last": data.get("lastPrice"),
            "close": data.get("lastPrice"),
            "baseVolume": (float(data["volume24"]) * contract_size
                           if data.get("volume24") is not None else None),
            "quoteVolume": data.get("amount24"), "info": dict(data),
        }
        with self._lock:
            self._last_ticker[symbol] = dict(data)
            oi = data.get("holdVol")
            if oi is not None:
                stamp = ticker["timestamp"]
                history = self._oi_history[symbol]
                if not history or history[-1]["timestamp"] != stamp:
                    history.append({
                        "timestamp": stamp,
                        "openInterestAmount": float(oi) * contract_size,
                    })
                    del history[:-200]
        return ticker

    def fetch_tickers(self, symbols=None, params=None):
        rows = self._get("/api/v1/contract/ticker") or []
        if isinstance(rows, dict):
            rows = [rows]
        requested = set(symbols or self.symbols or [])
        output = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = self.unified_symbol({
                "baseCoin": row.get("symbol", "").split("_")[0],
                "quoteCoin": row.get("symbol", "").split("_")[-1],
                "settleCoin": row.get("symbol", "").split("_")[-1],
            })
            if requested and symbol not in requested:
                continue
            output[symbol] = self._normalize_ticker(symbol, row)
        return output

    def fetch_ticker(self, symbol, params=None):
        data = self._get("/api/v1/contract/ticker",
                         {"symbol": self.market_id(symbol)})
        if isinstance(data, list):
            data = next((row for row in data if row.get("symbol") == self.market_id(symbol)), {})
        return self._normalize_ticker(symbol, data or {})

    def fetch_open_interest(self, symbol, params=None):
        self.fetch_ticker(symbol)
        with self._lock:
            data = dict(self._last_ticker.get(symbol) or {})
        value = data.get("holdVol")
        if value is None:
            return {}
        return {
            "symbol": symbol, "openInterestAmount": float(value) * self.contract_size(symbol),
            "openInterestValue": None,
            "timestamp": int(data.get("timestamp") or self.milliseconds()),
            "info": data,
        }

    def fetch_open_interest_history(self, symbol, timeframe="1h", since=None, limit=None, params=None):
        # MEXC's public futures API exposes current holdVol, not a historical
        # OI candle endpoint. Only return timestamped snapshots actually
        # observed by this process; never synthesize prior observations.
        self.fetch_ticker(symbol)
        with self._lock:
            rows = list(self._oi_history.get(symbol, []))
        if since is not None:
            rows = [row for row in rows if row["timestamp"] >= int(since)]
        return rows[-int(limit or 100):]

    def fetch_funding_rate(self, symbol, params=None):
        data = self._get(f"/api/v1/contract/funding_rate/{self.market_id(symbol)}") or {}
        return {
            "symbol": symbol, "fundingRate": float(data["fundingRate"]),
            "timestamp": int(data.get("timestamp") or self.milliseconds()),
            "nextFundingTimestamp": data.get("nextSettleTime"), "info": data,
        }

    def fetch_funding_rate_history(self, symbol, since=None, limit=100, params=None):
        data = self._get("/api/v1/contract/funding_rate/history", {
            "symbol": self.market_id(symbol), "page_num": 1,
            "page_size": min(max(int(limit or 100), 1), 1000),
        }) or {}
        rows = data.get("resultList") or []
        output = []
        for row in rows:
            try:
                stamp = int(row["settleTime"])
                if since is not None and stamp < int(since):
                    continue
                output.append({
                    "symbol": symbol, "timestamp": stamp,
                    "fundingRate": float(row["fundingRate"]), "info": row,
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return sorted(output, key=lambda item: item["timestamp"])[-int(limit or 100):]
