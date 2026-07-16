import ccxt

from data_engine import get_market_data
from engine import AtlasEngine

engine = AtlasEngine()

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

markets = exchange.load_markets()

for symbol in markets:

    if not symbol.endswith("/USDT:USDT"):
        continue

    try:

        data = get_market_data(symbol)

        result = engine.analyze(data["15m"])

        print(f"✓ {symbol}")

        if len(result["structure"]) > 0:

            print(
                "Son Yapı:",
                result["structure"][-1]["label"]
            )

    except Exception as e:

        print(f"HATA {symbol}: {e}")
