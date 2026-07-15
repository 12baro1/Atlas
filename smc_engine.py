import ccxt

class SMCEngine:

    def __init__(self):

        self.exchange = ccxt.bybit({
            "options": {
                "defaultType": "swap"
            },
            "enableRateLimit": True
        })

    def candles(self, symbol, timeframe, limit):

        return self.exchange.fetch_ohlcv(
            symbol,
            timeframe,
            limit=limit
        )

    def market_structure(self, candles):

        # GERÇEK ALGORİTMA BURAYA YAZILACAK
        pass

    def liquidity(self, candles):

        # GERÇEK ALGORİTMA BURAYA YAZILACAK
        pass

    def orderblock(self, candles):

        # GERÇEK ALGORİTMA BURAYA YAZILACAK
        pass

    def fvg(self, candles):

        # GERÇEK ALGORİTMA BURAYA YAZILACAK
        pass

    def choch(self, candles):

        # GERÇEK ALGORİTMA BURAYA YAZILACAK
        pass

    def bos(self, candles):

        # GERÇEK ALGORİTMA BURAYA YAZILACAK
        pass

    def score(self):

        score = 0

        return score

engine = SMCEngine()

btc = engine.candles("BTC/USDT:USDT","15m",1000)

print(len(btc))
