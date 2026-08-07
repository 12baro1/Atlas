import time
import ccxt
from core.candle import Candle

# Bybit API olmadan sadece public veri için exchange oluştur
exchange = ccxt.bybit({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})

TIMEFRAMES = {
    "1w": 300,
    "1d": 500,
    "4h": 1000,
    "1h": 1000,
    "15m": 1000,
}

# Üst TF'ler yavaş değişir; her taramada yeniden çekmek yerine TTL önbellek.
# 15m larç hızlı değiştiği için çok kısa TTL'li ya da önbelleksiz tutulur.
TF_CACHE_TTL_SECONDS = {
    "1w": 3600,
    "1d": 3600,
    "4h": 900,
    "1h": 300,
    "15m": 0,
}

_cache = {}


def _fetch(symbol, timeframe, limit):
    raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    return [
        Candle(time=c[0], open=c[1], high=c[2], low=c[3], close=c[4], volume=c[5])
        for c in raw
    ]


def fetch_candles(symbol, timeframe, limit, force_refresh=False):
    now = time.time()
    key = (symbol, timeframe)

    if not force_refresh and timeframe != "15m":
        cached = _cache.get(key)
        if cached is not None:
            candles, fetched_at = cached
            ttl = TF_CACHE_TTL_SECONDS.get(timeframe, 0)
            if now - fetched_at <= ttl:
                return candles

    candles = _fetch(symbol, timeframe, limit)
    _cache[key] = (candles, now)
    return candles


def invalidate_all():
    """Zorunlu tazeleme için en düşük seviyeli önbelleği boşaltır."""
    _cache.clear()


def get_market_data(symbol, force_refresh=False):
    data = {"symbol": symbol}

    for timeframe, c_limit in TIMEFRAMES.items():
        data[timeframe] = fetch_candles(symbol, timeframe, c_limit, force_refresh=force_refresh)

    return data