"""Bounded historical Gate futures reads for virtual position verification."""
from dataclasses import dataclass, field
from math import isfinite, isclose
from functools import lru_cache
from time import monotonic, sleep

from core.candle import convert
from gateio_futures import GateFuturesExchange, trade_timestamp_ms

MINUTE = 60_000
TEN_SECONDS = 10_000
BAR = 5 * MINUTE
QUARTER_HOUR = 15 * MINUTE


class EvidenceMissing(ValueError):
    pass


@dataclass
class TradeGroup:
    """Trades with no provable relative order inside one Gate timestamp."""
    time: int
    prices: set = field(default_factory=set)
    volume: float = 0


def trades_match(candle, groups):
    # Volume summation differs slightly across REST candlesticks and trades.
    # Keep OHLC prices exact and accept only negligible float rounding.
    return bool(groups and candle.open in groups[0].prices and candle.close in groups[-1].prices
                and min(min(g.prices) for g in groups) == candle.low
                and max(max(g.prices) for g in groups) == candle.high
                and isclose(sum(g.volume for g in groups), candle.volume,
                            rel_tol=1e-9, abs_tol=1e-8))


def indexed(candles, width, now):
    result = {}
    for candle in candles:
        if candle.time % width or candle.time + width > now:
            continue
        old = result.get(candle.time)
        if candle.time in result and old != candle:
            result[candle.time] = None
        else:
            result[candle.time] = candle
    return result


def matches(parent, children):
    return bool(children and children[0].open == parent.open and children[-1].close == parent.close
                and max(c.high for c in children) == parent.high and min(c.low for c in children) == parent.low
                and isclose(sum(c.volume for c in children), parent.volume,
                            rel_tol=1e-9, abs_tol=1e-8))


class TrackingHistory:
    """Per-worker cache of closed ranges. Volumes here are native contract counts."""
    def __init__(self):
        self.exchange = GateFuturesExchange(timeout=4, max_retries=1)
        self.last_request = 0
        self.candles = lru_cache(maxsize=32)(self._candles)
        self.ticks = lru_cache(maxsize=16)(self._ticks)

    def _get(self, endpoint, symbol, start, end, **params):
        sleep(max(0, self.last_request + 0.25 - monotonic()))
        self.last_request = monotonic()
        query = {'contract': self.exchange.market_id(symbol), 'from': start // 1000, 'to': (end - 1) // 1000, **params}
        return self.exchange._get('/futures/usdt/' + endpoint, query)

    def _candles(self, symbol, start, width, count):
        interval = "10s" if width == TEN_SECONDS else f"{width // MINUTE}m"
        rows = self._get('candlesticks', symbol, start, start + count * width, interval=interval)
        return convert([[int(r['t']) * 1000, r['o'], r['h'], r['l'], r['c'], r['v']] for r in rows])

    def _ticks(self, symbol, candle_time):
        return self.trade_range(symbol, candle_time, candle_time + MINUTE)

    def trade_range(self, symbol, start, end):
        """Fetch a complete trade interval, paging only when Gate truncates it.

        Gate's futures time-range endpoint returns at most 1000 records per
        request. Never use a partial page as proof of a fill or stop/TP order.
        """
        if end <= start:
            return []
        page_limit, max_pages = 1000, 8
        ticks, ids = {}, set()
        offset = 0
        complete = False
        for _ in range(max_pages):
            params = {"limit": page_limit}
            if offset:
                params["offset"] = offset
            rows = self._get("trades", symbol, start, end, **params)
            if not isinstance(rows, list):
                raise EvidenceMissing("Geçersiz Gate.io işlem geçmişi")
            if not rows:
                complete = True
                break
            for row in rows:
                try:
                    stamp = trade_timestamp_ms(row["create_time_ms"])
                    price = float(row["price"])
                    size = abs(float(row["size"]))
                    trade_id = row["id"]
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    raise EvidenceMissing("Geçersiz işlem kaydı") from exc
                if not isfinite(price) or not isfinite(size) or min(price, size) <= 0:
                    raise EvidenceMissing("Geçersiz işlem fiyatı veya hacmi")
                if not start <= stamp < end:
                    raise EvidenceMissing("İşlem geçmişi istenen aralık dışında")
                if trade_id in ids:
                    raise EvidenceMissing("Gate.io işlem sayfaları örtüşüyor")
                ids.add(trade_id)
                group = ticks.setdefault(stamp, TradeGroup(stamp))
                group.prices.add(price)
                group.volume += size
            if len(rows) < page_limit:
                complete = True
                break
            offset += len(rows)
        if not complete:
            raise EvidenceMissing("İşlem geçmişi sayfa sınırını aşıyor")
        if not ticks:
            raise EvidenceMissing("İşlem geçmişinde doğrulanabilir kayıt yok")
        return [ticks[t] for t in sorted(ticks)]
