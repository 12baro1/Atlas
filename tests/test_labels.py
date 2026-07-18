import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_RUN_LIVE_CCXT_TESTS") != "1",
    reason="Live ccxt tests are disabled; set ATLAS_RUN_LIVE_CCXT_TESTS=1 to run them.",
)

ccxt = pytest.importorskip("ccxt")

from core.candle import convert
from swing_engine import detect
from structure_labels import label_swings

exchange = ccxt.bybit({
    "options": {"defaultType": "swap"},
    "enableRateLimit": True
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
        round(x["price"], 2)
    )
