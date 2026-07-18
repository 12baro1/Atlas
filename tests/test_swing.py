import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt

from core.candle import convert
from core.swing_engine import detect

exchange=ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

markets = exchange.load_markets()
symbol = next((item for item in markets if item.endswith("/USDT:USDT")), "BTC/USDT:USDT")

raw=exchange.fetch_ohlcv(
    symbol,
    "15m",
    limit=300
)

candles=convert(raw)

swings=detect(candles)

print()

print("Swing Sayısı:",len(swings))

print()

for s in swings:

    print(s.kind,s.index,round(s.price,2))

