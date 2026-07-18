import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ccxt

from core.candle import convert
from core.market_structure_engine import MarketStructureEngine

exchange=ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

markets = exchange.load_markets()
symbol = next((item for item in markets if item.endswith("/USDT:USDT")), "BTC/USDT:USDT")

raw=exchange.fetch_ohlcv(
    symbol,
    "15m",
    limit=500
)

candles=convert(raw)

engine=MarketStructureEngine()

engine.find_pivots(candles)

engine.calculate_strength(candles)

engine.merge_pivots()

engine.filter_noise()

pivots=engine.validate_sequence()

print()

print("Toplam Pivot:",len(pivots))

print()

for p in pivots[-20:]:

    print(
        p.kind,
        round(p.price,2),
        p.strength
    )

