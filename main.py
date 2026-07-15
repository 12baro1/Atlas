import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    }
})

markets = exchange.load_markets()
count = 0

for symbol in markets:
    if symbol.endswith("/USDT:USDT"):
        print(symbol)
        count += 1

print(f"\nToplam USDT Futures: {count}")
