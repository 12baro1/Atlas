"""Read-only Gate.io USDT perpetual market-data adapter for Atlas."""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
import requests


BASE_URL = "https://api.gateio.ws/api/v4"


def _scaled_contract_amount(value, multiplier):
    """Scale Gate contract counts without binary-float multiplication drift."""
    try:
        amount = Decimal(str(value)) * Decimal(str(multiplier))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
    return float(amount) if amount.is_finite() else 0.0
_INTERVALS = {"1m":"1m", "5m":"5m", "15m":"15m", "30m":"30m",
              "1h":"1h", "4h":"4h", "1d":"1d", "1w":"7d"}


class GateFuturesExchange:
    id = "gateio"
    name = "Gate.io Futures"

    def __init__(self, session=None, timeout=15):
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.markets = {}
        self.symbols = []

    @staticmethod
    def milliseconds():
        return int(time.time() * 1000)

    @staticmethod
    def parse_timeframe(timeframe):
        units = {"m":60, "h":3600, "d":86400, "w":604800}
        return int(timeframe[:-1]) * units[timeframe[-1]]

    @staticmethod
    def market_id(symbol):
        value = str(symbol or "").upper().strip()
        if "_" in value and "/" not in value:
            return value
        return value.split(":")[0].replace("/", "_")

    @staticmethod
    def unified_symbol(contract):
        name = str(contract.get("name") or contract.get("contract") or "")
        parts = name.split("_")
        if len(parts) != 2:
            return ""
        return f"{parts[0]}/{parts[1]}:{parts[1]}"

    def _get(self, path, params=None):
        response = self.session.get(BASE_URL + path, params=params or {}, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("label") and payload.get("message"):
            raise RuntimeError(f"Gate.io API error: {payload.get('label')}: {payload.get('message')}")
        return payload

    def load_markets(self, reload=False, params=None):
        if self.markets and not reload:
            return self.markets
        rows = self._get("/futures/usdt/contracts") or []
        markets = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("in_delisting"):
                continue
            symbol = self.unified_symbol(row)
            if not symbol:
                continue
            markets[symbol] = {
                "id": row.get("name"), "symbol": symbol, "base": symbol.split("/")[0],
                "quote": "USDT", "settle": "USDT", "active": True,
                "swap": True, "spot": False, "future": False, "contract": True,
                "linear": True, "inverse": False, "contractSize": float(row.get("quanto_multiplier") or 1.0),
                "precision": {"price": row.get("order_price_round"), "amount": row.get("quanto_multiplier")},
                "limits": {"amount": {"min": row.get("order_size_min"), "max": row.get("order_size_max")}},
                "info": dict(row),
            }
        self.markets, self.symbols = markets, sorted(markets)
        return self.markets

    def market(self, symbol):
        if not self.markets:
            self.load_markets()
        return self.markets[symbol]

    def contract_size(self, symbol):
        """Return Gate.io quanto multiplier for this exact futures contract."""
        market = self.market(symbol)
        try:
            value = float(market.get("contractSize") or 1.0)
        except (TypeError, ValueError, OverflowError):
            value = 1.0
        return value if value > 0 else 1.0

    def fetch_ohlcv(self, symbol, timeframe="1m", since=None, limit=None, params=None):
        interval = _INTERVALS[timeframe]
        now_s = int(time.time())
        count = min(max(int(limit or 500), 1), 2000)
        query = {"contract": self.market_id(symbol), "interval": interval, "limit": count}
        if since is not None:
            query["from"] = int(since) // 1000
            query["to"] = min(now_s, query["from"] + self.parse_timeframe(timeframe) * count)
        rows = self._get("/futures/usdt/candlesticks", query) or []
        result = []
        for row in rows:
            try:
                result.append([int(row["t"]) * 1000, float(row["o"]), float(row["h"]),
                               float(row["l"]), float(row["c"]), _scaled_contract_amount(abs(float(row["v"])), self.contract_size(symbol))])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return sorted(result, key=lambda x: x[0])[-count:]

    def fetch_order_book(self, symbol, limit=50, params=None):
        data = self._get("/futures/usdt/order_book", {
            "contract": self.market_id(symbol), "limit": min(max(int(limit or 50), 1), 1000),
            "with_id": "true",
        }) or {}
        def levels(rows):
            out = []
            for row in rows or []:
                try:
                    price, size = float(row["p"]), _scaled_contract_amount(abs(float(row["s"])), self.contract_size(symbol))
                    if price > 0 and size > 0:
                        out.append([price, size])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
            return out
        stamp = int(data.get("t") or self.milliseconds())
        if stamp < 10_000_000_000:
            stamp *= 1000
        return {"symbol": symbol, "bids": levels(data.get("bids")), "asks": levels(data.get("asks")),
                "timestamp": stamp, "nonce": data.get("id"), "datetime": None}

    def fetch_trades(self, symbol, since=None, limit=100, params=None):
        rows = self._get("/futures/usdt/trades", {
            "contract": self.market_id(symbol), "limit": min(max(int(limit or 100), 1), 1000)
        }) or []
        out = []
        for row in rows:
            try:
                stamp = int(row["create_time_ms"])
                if since is not None and stamp < int(since):
                    continue
                size = _scaled_contract_amount(abs(float(row["size"])), self.contract_size(symbol))
                side = "buy" if float(row["size"]) > 0 else "sell"
                price = float(row["price"])
                out.append({"id": str(row.get("id", "")), "timestamp": stamp, "datetime": None,
                            "symbol": symbol, "type": None, "side": side, "price": price,
                            "amount": size, "cost": price * size, "info": dict(row)})
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return sorted(out, key=lambda x: x["timestamp"])[-int(limit or 100):]

    def fetch_ticker(self, symbol, params=None):
        row = self._get("/futures/usdt/tickers", {"contract": self.market_id(symbol)})
        if isinstance(row, list):
            row = row[0] if row else {}
        row = row or {}
        stamp = self.milliseconds()
        return {"symbol": symbol, "timestamp": stamp, "datetime": None,
                "high": row.get("high_24h"), "low": row.get("low_24h"),
                "bid": row.get("highest_bid"), "ask": row.get("lowest_ask"),
                "last": row.get("last"), "close": row.get("last"),
                "baseVolume": _scaled_contract_amount(row.get("volume_24h") or 0, self.contract_size(symbol)), "quoteVolume": row.get("volume_24h_quote"),
                "info": dict(row)}

    def fetch_tickers(self, symbols=None, params=None):
        rows = self._get("/futures/usdt/tickers") or []
        wanted = set(symbols or self.symbols or [])
        out = {}
        for row in rows:
            symbol = self.unified_symbol(row)
            if symbol and (not wanted or symbol in wanted):
                # Keep a single consistent normalizer and avoid per-market requests.
                out[symbol] = {"symbol": symbol, "timestamp": self.milliseconds(), "datetime": None,
                    "high": row.get("high_24h"), "low": row.get("low_24h"),
                    "bid": row.get("highest_bid"), "ask": row.get("lowest_ask"),
                    "last": row.get("last"), "close": row.get("last"),
                    "baseVolume": (float(row.get("volume_24h") or 0) * self.contract_size(symbol)), "quoteVolume": row.get("volume_24h_quote"),
                    "info": dict(row)}
        return out

    def fetch_open_interest(self, symbol, params=None):
        rows = self._get("/futures/usdt/contract_stats", {
            "contract": self.market_id(symbol), "interval": "1m", "limit": 1
        }) or []
        row = rows[-1] if rows else {}
        value = row.get("open_interest")
        return {"symbol": symbol, "openInterestAmount": _scaled_contract_amount(value, self.contract_size(symbol)) if value is not None else None,
                "openInterestValue": None, "timestamp": int(row.get("time") or self.milliseconds()),
                "info": dict(row)}

    def fetch_open_interest_history(self, symbol, timeframe="1h", since=None, limit=100, params=None):
        rows = self._get("/futures/usdt/contract_stats", {
            "contract": self.market_id(symbol), "interval": _INTERVALS.get(timeframe, "1h"),
            "limit": min(max(int(limit or 100), 1), 1000)
        }) or []
        out = []
        for row in rows:
            try:
                stamp = int(row.get("time") or 0)
                if stamp < 10_000_000_000:
                    stamp *= 1000
                if since is not None and stamp < int(since):
                    continue
                out.append({"timestamp": stamp, "openInterestAmount": _scaled_contract_amount(row["open_interest"], self.contract_size(symbol))})
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return out

    def fetch_funding_rate(self, symbol, params=None):
        row = self._get("/futures/usdt/funding_rate", {"contract": self.market_id(symbol)}) or {}
        if isinstance(row, list):
            row = row[0] if row else {}
        return {"symbol": symbol, "fundingRate": float(row.get("r", row.get("funding_rate", 0))),
                "timestamp": int(row.get("t") or self.milliseconds()), "info": dict(row)}

    def fetch_funding_rate_history(self, symbol, since=None, limit=100, params=None):
        rows = self._get("/futures/usdt/funding_rate", {
            "contract": self.market_id(symbol), "limit": min(max(int(limit or 100), 1), 1000)
        }) or []
        out = []
        for row in rows if isinstance(rows, list) else [rows]:
            try:
                stamp = int(row.get("t") or 0)
                if stamp < 10_000_000_000:
                    stamp *= 1000
                if since is not None and stamp < int(since):
                    continue
                out.append({"symbol": symbol, "timestamp": stamp,
                            "fundingRate": float(row.get("r", row.get("funding_rate"))), "info": dict(row)})
            except (TypeError, ValueError, OverflowError):
                continue
        return sorted(out, key=lambda x: x["timestamp"])[-int(limit or 100):]
