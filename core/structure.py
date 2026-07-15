import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

def get_candles(symbol, timeframe="15m", limit=1000):
    return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

def swing_points(candles, left=5, right=5):
    swings = []

    for i in range(left, len(candles) - right):

        high = candles[i][2]
        low = candles[i][3]

        is_high = True
        is_low = True

        for j in range(i-left, i+right+1):

            if j == i:
                continue

            if candles[j][2] >= high:
                is_high = False

            if candles[j][3] <= low:
                is_low = False

        if is_high:
            swings.append({
                "type": "HIGH",
                "index": i,
                "price": high
            })

        if is_low:
            swings.append({
                "type": "LOW",
                "index": i,
                "price": low
            })

    return sorted(swings, key=lambda x: x["index"])


candles = get_candles("BTC/USDT:USDT")

swings = swing_points(candles)

print(f"Toplam Swing : {len(swings)}\n")

for s in swings[-30:]:
    print(s)
