import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

TIMEFRAMES = {
    "1w": 300,
    "1d": 500,
    "4h": 1000,
    "1h": 1000,
    "15m": 1000
}

def get_market_data(symbol):

    data = {}

    for timeframe, limit in TIMEFRAMES.items():

        data[timeframe] = exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=limit
        )

    return data


btc = get_market_data("BTC/USDT:USDT")

print()

for tf in btc:

    print(tf, "=>", len(btc[tf]), "mum")

