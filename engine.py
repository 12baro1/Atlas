import ccxt

class SMCEngine:

    def __init__(self):

        self.exchange = ccxt.bybit({
            "options": {
                "defaultType": "swap"
            },
            "enableRateLimit": True
        })

    def get_candles(self, symbol, timeframe, limit):

        return self.exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=limit
        )

    def scan(self, symbol):

        print(f"\nAnaliz Başladı -> {symbol}")

        weekly = self.get_candles(symbol, "1w", 300)
        daily = self.get_candles(symbol, "1d", 500)
        h4 = self.get_candles(symbol, "4h", 1000)
        h1 = self.get_candles(symbol, "1h", 1000)
        m15 = self.get_candles(symbol, "15m", 1000)

        print("Weekly :", len(weekly))
        print("Daily  :", len(daily))
        print("H4     :", len(h4))
        print("H1     :", len(h1))
        print("M15    :", len(m15))

engine = SMCEngine()

engine.scan("BTC/USDT:USDT")
