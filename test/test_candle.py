import ccxt
from candle import convert

exchange=ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

raw=exchange.fetch_ohlcv("BTC/USDT:USDT","15m",limit=3)

candles=convert(raw)

for c in candles:

    print("="*40)
    print(c.date)
    print("Bull :",c.bullish)
    print("Bear :",c.bearish)
    print("Body :",round(c.body,2))
    print("Range:",round(c.range,2))
    print("Upper:",round(c.upper_wick,2))
    print("Lower:",round(c.lower_wick,2))

