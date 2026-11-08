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
    # limit'i anahtara kat: aynı sembol/ZF farklı limitlerle istenirse
    # birbirinin önbellek kaydını kirletip warmup eksikliği yaratmasın.
    key = (symbol, timeframe, limit)

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
    """Zorunlu tazeleme için tüm piyasa veri önbelleklerini boşaltır."""
    _cache.clear()
    if "_smt_cache" in globals():
        _smt_cache.clear()


def get_market_data(symbol, force_refresh=False):
    data = {"symbol": symbol}
    # Public Bybit order-book snapshot; optional so OHLCV analysis survives API hiccups.
    try:
        data["orderbook"] = exchange.fetch_order_book(symbol, limit=50)
    except Exception:
        data["orderbook"] = None

    # Recent executed trades provide taker buy/sell delta. This is a short
    # rolling sample, not a historical cumulative-volume-delta series.
    try:
        data["recent_trades"] = exchange.fetch_trades(symbol, limit=200)
    except Exception:
        data["recent_trades"] = None

    # Derivatives context is optional: unsupported endpoints or exchange
    # hiccups must not break OHLCV analysis.
    data["open_interest"] = []
    fetch_oi = getattr(exchange, "fetch_open_interest_history", None)
    if callable(fetch_oi):
        try:
            records = fetch_oi(symbol, timeframe="1h", limit=100) or []
            records = sorted(records, key=lambda item: item.get("timestamp") or 0)
            data["open_interest"] = [
                float(item.get("openInterestValue") or item.get("openInterestAmount"))
                for item in records
                if isinstance(item, dict)
                and (item.get("openInterestValue") is not None or item.get("openInterestAmount") is not None)
            ]
        except Exception:
            data["open_interest"] = []
    if not data["open_interest"]:
        fetch_oi_snapshot = getattr(exchange, "fetch_open_interest", None)
        if callable(fetch_oi_snapshot):
            try:
                snapshot = fetch_oi_snapshot(symbol) or {}
                value = snapshot.get("openInterestValue") or snapshot.get("openInterestAmount")
                if value is not None:
                    data["open_interest"] = [float(value)]
            except Exception:
                pass

    data["funding_rate"] = []
    fetch_funding_history = getattr(exchange, "fetch_funding_rate_history", None)
    if callable(fetch_funding_history):
        try:
            records = fetch_funding_history(symbol, limit=100) or []
            records = sorted(records, key=lambda item: item.get("timestamp") or 0)
            data["funding_rate"] = [
                float(item.get("fundingRate"))
                for item in records
                if isinstance(item, dict) and item.get("fundingRate") is not None
            ]
        except Exception:
            data["funding_rate"] = []
    if not data["funding_rate"]:
        fetch_funding = getattr(exchange, "fetch_funding_rate", None)
        if callable(fetch_funding):
            try:
                snapshot = fetch_funding(symbol) or {}
                value = snapshot.get("fundingRate")
                if value is not None:
                    data["funding_rate"] = [float(value)]
            except Exception:
                pass

    for timeframe, c_limit in TIMEFRAMES.items():
        data[timeframe] = fetch_candles(symbol, timeframe, c_limit, force_refresh=force_refresh)

    return data


# Korrelasyon evreni: BTC/ETH (dominance endeksleri Bybit'te yok; oysalar UNKNOWN
# kalir ve korrelasyon motoru yalnizca gercek veriye dayanarak engel karari verir).
_CORRELATION_SYMBOLS = {
    "BTC": ("BTC/USDT:USDT", "4h", 200),
    "ETH": ("ETH/USDT:USDT", "4h", 200),
}


def get_correlation_universe(force_refresh=False, candle_factory=None):
    """BTC/ETH 4h mumlarini toplar; scan boyunca cache toplar (bir kez cekilir)."""
    from core.candle import Candle
    universe = {}
    for key, (symbol, timeframe, limit) in _CORRELATION_SYMBOLS.items():
        try:
            candles = fetch_candles(symbol, timeframe, limit, force_refresh=force_refresh)
            universe[key] = candles
        except Exception:
            universe[key] = []
    return universe

# SMT comparison data is shared across a scan and cached per timeframe.
# 15m data gets a short TTL so scanning many symbols does not refetch BTC/ETH
# for every altcoin; higher timeframes use progressively longer TTLs.
_SMT_SYMBOLS = ("BTC/USDT:USDT", "ETH/USDT:USDT")
_SMT_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_SMT_CACHE_TTL_SECONDS = {"15m": 45, "1h": 300, "4h": 900, "1d": 3600}
_smt_cache = {}


def get_smt_universe(force_refresh=False):
    """Return cached BTC/ETH OHLCV comparison data for SMT on all supported TFs."""
    now = time.time()
    universe = {}
    for symbol in _SMT_SYMBOLS:
        frames = {}
        for timeframe in _SMT_TIMEFRAMES:
            key = (symbol, timeframe)
            cached = _smt_cache.get(key)
            ttl = _SMT_CACHE_TTL_SECONDS[timeframe]
            if (
                not force_refresh
                and cached is not None
                and now - cached[1] <= ttl
            ):
                frames[timeframe] = cached[0]
                continue
            try:
                candles = fetch_candles(symbol, timeframe, TIMEFRAMES[timeframe], force_refresh=force_refresh)
                _smt_cache[key] = (candles, now)
                frames[timeframe] = candles
            except Exception:
                # A temporary exchange failure should not erase a previously
                # fetched comparison series; the SMT engine can still use it.
                frames[timeframe] = cached[0] if cached is not None else []
        universe[symbol] = frames
    return universe
