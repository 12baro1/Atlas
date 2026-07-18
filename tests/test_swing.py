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

raw=exchange.fetch_ohlcv(
    "BTC/USDT:USDT",
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

