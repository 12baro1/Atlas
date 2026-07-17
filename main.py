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
        print(data["symbol"])

        result = engine.analyze(data)

        if result is None:
            continue

        analysis = result["analysis"]

        print(f"\n✓ {symbol}")

        if len(analysis["structure"]) > 0:
            print("Son Yapı :", analysis["structure"][-1]["label"])

        print("Liquidity :", len(analysis["liquidity"]))
        print("OrderBlocks :", len(analysis["orderblocks"]))
        print("FVG :", len(analysis["fvg"]))

        print("Signal :", result["signal"]["signal"])
        print("Confidence :", result["signal"]["confidence"])
        print("Grade :", result["signal"]["grade"])
        print("Strength :", result["signal"]["strength"])

        print("Trend :", analysis["trend"]["trend"])

        print("Entry :", analysis["entry"]["direction"])
        print("Entry Price :", analysis["entry"]["entry"])
        print("Stop Loss :", analysis["entry"]["stop_loss"])
        print("Entry Valid :", analysis["entry"]["valid"])
        print("Reason :", analysis["entry"]["reason"])

        print("Confirmed :", analysis["confirmation"]["confirmed"])
        print("Confirm Reason :", analysis["confirmation"]["reason"])

        print("Weekly :", analysis["mtf"]["weekly"])
        print("Daily :", analysis["mtf"]["daily"])
        print("H4 :", analysis["mtf"]["h4"])
        print("Entry TF :", analysis["mtf"]["entry"])
        print("MTF Valid :", analysis["mtf"]["valid"])

        print("TP1 :", result["dynamic_tp"]["tp1"])
        print("TP2 :", result["dynamic_tp"]["tp2"])
        print("TP3 :", result["dynamic_tp"]["tp3"])

        if result["risk"]:

            print("----- RISK -----")
            print("Capital Risk :", result["risk"]["capital_at_risk"])
            print("Position Size :", result["risk"]["position_size"])
            print("Risk :", result["risk"]["risk"])

        print("--------------------------------")

    except Exception:
        import traceback
        traceback.print_exc()
