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

        result = engine.analyze(data)

        print(f"\n✓ {symbol}")

        if len(result["structure"]) > 0:

            print("Son Yapı:", result["structure"][-1]["label"])

        print("Liquidity :", len(result["liquidity"]))
        print("OrderBlocks :", len(result["orderblocks"]))
        print("Mitigation :", len(result["mitigation"]))
        print("FVG :", len(result["fvg"]))
        print("Signal :", result["signal"]["signal"])
        print("Score :", result["signal"]["score"])
        print("Trend :", result["trend"])
        print("Weekly :", result["mtf"]["weekly"])
        print("Daily  :", result["mtf"]["daily"])
        print("H4     :", result["mtf"]["h4"])
        print("Entry  :", result["mtf"]["entry"])
        print("Valid  :", result["mtf"]["valid"])

        print("--------------------------------")

    except Exception as e:

        print(f"HATA {symbol}: {e}")
