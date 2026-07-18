import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt

from core.candle import convert
from utils.atr import atr

exchange = ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

markets = exchange.load_markets()
symbol = next((item for item in markets if item.endswith("/USDT:USDT")), "BTC/USDT:USDT")

raw = exchange.fetch_ohlcv(
    symbol,
    "15m",
    limit=100
)

candles = convert(raw)

print()

print("ATR =", round(atr(candles),2))

