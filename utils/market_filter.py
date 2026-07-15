import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType":"swap"
    },
    "enableRateLimit":True
})

TIMEFRAMES={
    "1w":300,
    "1d":500,
    "4h":500
}

def get(symbol,timeframe,limit):
    return exchange.fetch_ohlcv(symbol,timeframe,limit=limit)

def trend(data):

    closes=[x[4] for x in data]

    ema20=sum(closes[-20:])/20
    ema50=sum(closes[-50:])/50

    if ema20>ema50:
        return "BULL"

    return "BEAR"

coins=[
"BTC/USDT:USDT",
"ETH/USDT:USDT",
"SOL/USDT:USDT",
"XRP/USDT:USDT",
"SUI/USDT:USDT"
]

print()

for coin in coins:

    print("="*50)
    print(coin)

    for tf in TIMEFRAMES:

        data=get(coin,tf,TIMEFRAMES[tf])

        print(tf,"=>",trend(data))

    print()

