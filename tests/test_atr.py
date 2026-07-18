import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_RUN_LIVE_CCXT_TESTS") != "1",
    reason="Live ccxt tests are disabled; set ATLAS_RUN_LIVE_CCXT_TESTS=1 to run them.",
)

ccxt = pytest.importorskip("ccxt")

from core.candle import convert
from utils.atr import atr

exchange = ccxt.bybit({
    "options": {"defaultType": "swap"},
    "enableRateLimit": True
})

raw = exchange.fetch_ohlcv(
    "BTC/USDT:USDT",
    "15m",
    limit=100
)

candles = convert(raw)

print()

print("ATR =", round(atr(candles), 2))
