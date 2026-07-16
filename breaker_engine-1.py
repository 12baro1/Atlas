from core.market_state import MarketState

class BreakerEngine:
    def __init__(self):
        self.state=MarketState()
    def analyze(self,pivots):
        self.state.bos=False
        self.state.choch=False
        if len(pivots)<4:
            return self.state
        highs=[p for p in pivots if p.kind=='HIGH']
        lows=[p for p in pivots if p.kind=='LOW']
        if len(highs)>=2 and highs[-1].price>highs[-2].price:
            self.state.bos=True
            self.state.trend='BULLISH'
            self.state.last_hh=highs[-1].price
            self.state.notes.append('Bullish BOS')
        if len(lows)>=2 and lows[-1].price<lows[-2].price:
            self.state.bos=True
            self.state.trend='BEARISH'
            self.state.last_ll=lows[-1].price
            self.state.notes.append('Bearish BOS')
        return self.state
