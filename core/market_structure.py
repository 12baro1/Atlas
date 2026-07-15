import ccxt

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    },
    "enableRateLimit": True
})

def candles(symbol,timeframe,limit):

    return exchange.fetch_ohlcv(symbol,timeframe,limit=limit)

def pivots(data,left=10,right=10):

    points=[]

    for i in range(left,len(data)-right):

        high=data[i][2]
        low=data[i][3]

        isHigh=True
        isLow=True

        for j in range(i-left,i+right+1):

            if j==i:
                continue

            if data[j][2]>=high:
                isHigh=False

            if data[j][3]<=low:
                isLow=False

        if isHigh:
            points.append(("HIGH",i,high))

        if isLow:
            points.append(("LOW",i,low))

    return points

btc=candles("BTC/USDT:USDT","4h",500)

swings=pivots(btc)

print()

for s in swings:

    print(s)

print()

print("Toplam Swing:",len(swings))
