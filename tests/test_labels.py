import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt

from core.candle import convert
from core.swing_engine import detect
from utils.structure_labels import label_swings

exchange = ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

raw = exchange.fetch_ohlcv(
    "BTC/USDT:USDT",
    "15m",
    limit=300
)

candles = convert(raw)

swings = detect(candles)

labels = label_swings(swings)

print()

for x in labels:

    print(
        x["label"],
        x["type"],
        round(x["price"],2)
    )

