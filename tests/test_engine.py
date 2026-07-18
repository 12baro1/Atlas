import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_RUN_LIVE_CCXT_TESTS") != "1",
    reason="Live ccxt tests are disabled; set ATLAS_RUN_LIVE_CCXT_TESTS=1 to run them.",
)

ccxt = pytest.importorskip("ccxt")

from core.candle import convert
from core.market_structure_engine import MarketStructureEngine

exchange = ccxt.bybit({
    "options": {"defaultType": "swap"},
    "enableRateLimit": True
})

raw = exchange.fetch_ohlcv(
    "BTC/USDT:USDT",
    "15m",
    limit=500
)

candles = convert(raw)

engine = MarketStructureEngine()

engine.find_pivots(candles)

engine.calculate_strength(candles)

engine.merge_pivots()

engine.filter_noise()

pivots = engine.validate_sequence()

print()

print("Toplam Pivot:", len(pivots))

print()

for p in pivots[-20:]:

    print(
        p.kind,
        round(p.price, 2),
        p.strength
    )
