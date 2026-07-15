import ccxt

from candle import convert
from atr import atr

exchange = ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

raw = exchange.fetch_ohlcv(
    "BTC/USDT:USDT",
    "15m",
    limit=100
)

candles = convert(raw)

print()

print("ATR =", round(atr(candles),2))

