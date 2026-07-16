import ccxt
from core.candle import Candle

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

TIMEFRAMES = {
    "1w": 300,
    "1d": 500,
    "4h": 1000,
    "1h": 1000,
    "15m": 1000
}


def fetch_candles(symbol, timeframe, limit):

    raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    candles = []

    for c in raw:
        candles.append(
            Candle(
                time=c[0],
                open=c[1],
                high=c[2],
                low=c[3],
                close=c[4],
                volume=c[5]
            )
        )

    return candles


def get_market_data(symbol):

    data = {}

    for timeframe, limit in TIMEFRAMES.items():
        data[timeframe] = fetch_candles(symbol, timeframe, limit)

    return data
