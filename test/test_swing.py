import ccxt
from candle import convert
from swing_engine import detect

exchange=ccxt.bybit({
    "options":{"defaultType":"swap"},
    "enableRateLimit":True
})

raw=exchange.fetch_ohlcv(
    "BTC/USDT:USDT",
    "15m",
    limit=300
)

candles=convert(raw)

swings=detect(candles)

print()

print("Swing Sayısı:",len(swings))

print()

for s in swings:

    print(s.kind,s.index,round(s.price,2))

