import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

markets = exchange.load_markets()

symbols = []

for symbol in markets:
    if symbol.endswith("/USDT:USDT"):
        symbols.append(symbol)

print(f"\nToplam Coin: {len(symbols)}\n")

for i, symbol in enumerate(symbols, 1):
    try:
        candles = exchange.fetch_ohlcv(symbol, "15m", limit=100)

        if len(candles) > 0:
            print(f"[{i}/{len(symbols)}] ✅ {symbol} ({len(candles)} mum)")
        else:
            print(f"[{i}/{len(symbols)}] ❌ {symbol}")

    except Exception as e:
        print(f"[{i}/{len(symbols)}] HATA {symbol}: {e}")
