import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType":"swap"
    },
    "enableRateLimit":True
})

markets=exchange.load_markets()

coins=[]

for symbol in markets:

    if symbol.endswith("/USDT:USDT"):

        if markets[symbol]["active"]:

            coins.append(symbol)

coins=sorted(coins)

print()

print("TOPLAM COIN :",len(coins))

print()

for i,c in enumerate(coins):

    print(f"{i+1}. {c}")

