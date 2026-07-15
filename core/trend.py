import ccxt

exchange = ccxt.bybit({
    "options": {"defaultType": "swap"},
    "enableRateLimit": True
})

def trend(symbol, timeframe):

    candles = exchange.fetch_ohlcv(symbol, timeframe, limit=250)

    highs = [x[2] for x in candles[-50:]]
    lows = [x[3] for x in candles[-50:]]

    hh = max(highs)
    ll = min(lows)

    last = candles[-1][4]

    if last > (hh + ll) / 2:
        return "BULLISH"

    return "BEARISH"


symbol = "BTC/USDT:USDT"

print("Weekly :", trend(symbol, "1w"))
print("Daily  :", trend(symbol, "1d"))
print("H4     :", trend(symbol, "4h"))
print("H1     :", trend(symbol, "1h"))
print("M15    :", trend(symbol, "15m"))
