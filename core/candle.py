from dataclasses import dataclass
from datetime import datetime

@dataclass
class Candle:

    time:int
    open:float
    high:float
    low:float
    close:float
    volume:float

    @property
    def bullish(self):
        return self.close > self.open

    @property
    def bearish(self):
        return self.close < self.open

    @property
    def body(self):
        return abs(self.close-self.open)

    @property
    def range(self):
        return self.high-self.low

    @property
    def upper_wick(self):
        return self.high-max(self.open,self.close)

    @property
    def lower_wick(self):
        return min(self.open,self.close)-self.low

    @property
    def date(self):
        return datetime.fromtimestamp(self.time/1000)

def convert(data):

    candles=[]

    for c in data:

        candles.append(
            Candle(
                c[0],
                c[1],
                c[2],
                c[3],
                c[4],
                c[5]
            )
        )

    return candles

