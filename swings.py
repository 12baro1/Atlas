import ccxt

exchange = ccxt.bybit({
    "options": {"defaultType": "swap"},
    "enableRateLimit": True
})

symbol = "BTC/USDT:USDT"

candles = exchange.fetch_ohlcv(symbol, "15m", limit=300)

threshold = 0.5  # %0.5

last_high = candles[0][2]
last_low = candles[0][3]

print(f"\n{symbol}\n")

for i, candle in enumerate(candles):

    high = candle[2]
    low = candle[3]

    if ((high - last_high) / last_high) * 100 >= threshold:
        print(f"SWING HIGH -> Mum {i}  Fiyat: {high}")
        last_high = high

    if ((last_low - low) / last_low) * 100 >= threshold:
        print(f"SWING LOW  -> Mum {i}  Fiyat: {low}")
        last_low = low
