"""Read-only Gate.io USDT perpetual market-data adapter for Atlas."""
from __future__ import annotations

import os
import math
import time
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import requests


_request_metrics = threading.local()


@dataclass
class RequestMetrics:
    count: int = 0
    seconds: float = 0.0
    last_response: float = 0.0


def request_metrics():
    """Counters owned by one worker, also readable by its supervisor."""
    metrics = getattr(_request_metrics, "value", None)
    if metrics is None:
        metrics = _request_metrics.value = RequestMetrics()
    return metrics


BASE_URL = "https://api.gateio.ws/api/v4"


def trade_timestamp_ms(value):
    """Gate sends both milliseconds and fractional Unix seconds in create_time_ms."""
    try:
        stamp = Decimal(str(value))
        return int(stamp * 1000 if stamp < 10_000_000_000 else stamp)
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise ValueError("Invalid Gate trade timestamp") from exc


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

    def __init__(
        self,
        session=None,
        timeout=15,
        max_retries=None,
        retry_backoff_seconds=None,
    ):
        self.session = session or requests.Session()
        if session is None:
            # Keep fractional contracts in REST candles, trades and depth.
            self.session.headers["X-Gate-Size-Decimal"] = "1"
        self.timeout = float(timeout)
        self.max_retries = max(
            1,
            int(max_retries if max_retries is not None else os.getenv("ATLAS_GATEIO_MAX_RETRIES", "3")),
        )
        self.retry_backoff_seconds = max(
            0.0,
            float(
                retry_backoff_seconds
                if retry_backoff_seconds is not None
                else os.getenv("ATLAS_GATEIO_RETRY_BACKOFF_SECONDS", "1.0")
            ),
        )
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
        """GET a public Gate.io endpoint, retrying only transient transport/server failures."""
        retryable_statuses = {429, 500, 502, 503, 504}
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            started = time.monotonic()
            try:
                response = self.session.get(
                    BASE_URL + path,
                    params=params or {},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("label") and payload.get("message"):
                    raise RuntimeError(
                        f"Gate.io API error: {payload.get('label')}: {payload.get('message')}"
                    )
                return payload
            except requests.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status not in retryable_statuses or attempt >= self.max_retries:
                    raise
                last_error = exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise
                last_error = exc

            finally:
                metrics = request_metrics()
                metrics.last_response = time.monotonic()
                metrics.count += 1
                metrics.seconds += metrics.last_response - started

            delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
            if delay > 0:
                time.sleep(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Gate.io request failed without a response: {path}")

    def load_markets(self, reload=False, params=None):
        if self.markets and not reload:
            return self.markets
        rows = self._get("/futures/usdt/contracts") or []
        markets = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("in_delisting"):
                continue
            status = str(row.get("status") or "").strip().lower()
            # Only active contracts are eligible for new analysis/setups.
            # Prelaunch, delisting, delisted and circuit-breaker contracts are excluded.
            if status and status != "trading":
                continue
            symbol = self.unified_symbol(row)
            if not symbol:
                continue
            markets[symbol] = {
                "id": row.get("name"), "symbol": symbol, "base": symbol.split("/")[0],
                "quote": "USDT", "settle": "USDT", "active": True, "status": status or "trading",
                "contract_type": row.get("contract_type"),
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
            del query["limit"]
            query["from"] = (int(since) + 999) // 1000
            if query["from"] > now_s:
                return []
            query["to"] = min(now_s, query["from"] + self.parse_timeframe(timeframe) * count - 1)
        rows = self._get("/futures/usdt/candlesticks", query) or []
        by_time = {}
        multiplier = self.contract_size(symbol) if rows else None
        for row in rows:
            try:
                if since is not None and int(row["t"]) * 1000 < since:
                    continue
                stamp = int(row["t"]) * 1000
                candle = [stamp, float(row["o"]), float(row["h"]), float(row["l"]), float(row["c"]),
                          _scaled_contract_amount(abs(float(row["v"])), multiplier)]
                # Conflicting duplicates leave a gap for historical verification.
                if stamp in by_time and by_time[stamp] != candle:
                    by_time[stamp] = None
                else:
                    by_time[stamp] = candle
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return [by_time[t] for t in sorted(by_time) if by_time[t] is not None][-count:]

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
            if not isinstance(row, dict) or row.get("is_internal") is True:
                continue
            try:
                stamp = trade_timestamp_ms(row["create_time_ms"])
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
        stamp = int(row.get("time") or self.milliseconds())
        if stamp < 10_000_000_000:
            stamp *= 1000
        raw_usd = row.get("open_interest_usd")
        return {"symbol": symbol, "openInterestAmount": _scaled_contract_amount(value, self.contract_size(symbol)) if value is not None else None,
                "openInterestValue": float(raw_usd) if raw_usd is not None else None,
                "timestamp": stamp, "info": dict(row)}

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
                raw_usd = row.get("open_interest_usd")
                out.append({"timestamp": stamp,
                            "openInterestAmount": _scaled_contract_amount(row["open_interest"], self.contract_size(symbol)),
                            "openInterestValue": float(raw_usd) if raw_usd is not None else None})
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return sorted(out, key=lambda row: row["timestamp"])

    def fetch_funding_rate(self, symbol, params=None):
        rows = self.fetch_funding_rate_history(symbol, limit=1, params=params)
        return rows[-1] if rows else {"symbol": symbol, "fundingRate": None,
                                     "timestamp": None, "info": {}}

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
                rate = float(row.get("r", row.get("funding_rate")))
                if stamp > 0 and math.isfinite(rate):
                    out.append({"symbol": symbol, "timestamp": stamp,
                                "fundingRate": rate, "info": dict(row)})
            except (TypeError, ValueError, OverflowError):
                continue
        return sorted(out, key=lambda x: x["timestamp"])[-int(limit or 100):]
