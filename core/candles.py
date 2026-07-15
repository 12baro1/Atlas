import ccxt
from datetime import datetime

exchange = ccxt.bybit({
    "options": {
        "defaultType": "swap"
    }
})

symbol = "BTC/USDT:USDT"
timeframe = "15m"
limit = 1000

candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

print(f"\n{symbol}")
print(f"Toplam Mum: {len(candles)}\n")

for candle in candles[-10:]:
    zaman = datetime.utcfromtimestamp(candle[0] / 1000)
    print(f"""
Tarih  : {zaman}
Open   : {candle[1]}
High   : {candle[2]}
Low    : {candle[3]}
Close  : {candle[4]}
Volume : {candle[5]}
------------------------------
""")
