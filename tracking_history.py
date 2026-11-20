"""Bounded historical Gate futures reads for virtual position verification."""
from dataclasses import dataclass, field
from math import isfinite
from functools import lru_cache
from time import monotonic, sleep

from core.candle import convert
from gateio_futures import GateFuturesExchange, trade_timestamp_ms

MINUTE = 60_000
BAR = 15 * MINUTE


class EvidenceMissing(ValueError):
    pass


@dataclass
class TradeGroup:
    """Trades with no provable relative order inside one Gate timestamp."""
    time: int
    prices: set = field(default_factory=set)
    volume: float = 0


def trades_match(candle, groups):
    return bool(groups and candle.open in groups[0].prices and candle.close in groups[-1].prices
                and min(min(g.prices) for g in groups) == candle.low
                and max(max(g.prices) for g in groups) == candle.high
                and sum(g.volume for g in groups) == candle.volume)


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
                and sum(c.volume for c in children) == parent.volume)


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
        rows = self._get('candlesticks', symbol, start, start + count * width, interval=f'{width // MINUTE}m')
        return convert([[int(r['t']) * 1000, r['o'], r['h'], r['l'], r['c'], r['v']] for r in rows])

    def _ticks(self, symbol, candle_time):
        return self.trade_range(symbol, candle_time, candle_time + MINUTE)

    def trade_range(self, symbol, start, end):
        rows = self._get('trades', symbol, start, end, limit=1000)
        if not rows or len(rows) >= 1000:
            raise EvidenceMissing("1m işlem geçmişi eksik veya sayfa sınırında")
        ticks = {}
        ids = set()
        for row in rows:
            stamp = trade_timestamp_ms(row['create_time_ms'])
            price, size = float(row['price']), abs(float(row['size']))
            if not isfinite(price) or not isfinite(size) or min(price, size) <= 0:
                raise EvidenceMissing("Geçersiz işlem fiyatı veya hacmi")
            if not start <= stamp < end or row['id'] in ids:
                raise EvidenceMissing("1m işlem geçmişi aralık veya kimlik uyuşmazlığı")
            ids.add(row['id'])
            if stamp not in ticks:
                ticks[stamp] = TradeGroup(stamp)
            ticks[stamp].prices.add(price)
            ticks[stamp].volume += size
        return [ticks[t] for t in sorted(ticks)]
