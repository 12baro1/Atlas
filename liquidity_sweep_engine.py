"""
liquidity_sweep_engine.py
Atlas SMC Engine
"""

class LiquiditySweepEngine:
    """
    Detects buy-side and sell-side liquidity sweeps.
    """

    def detect(self, candles):

        if len(candles) < 3:
            return {
                "buy_side": False,
                "sell_side": False,
                "swept_high": None,
                "swept_low": None
            }

        prev = candles[-2]
        last = candles[-1]

        buy_side = last.high > prev.high and last.close < prev.high
        sell_side = last.low < prev.low and last.close > prev.low

        return {
            "buy_side": buy_side,
            "sell_side": sell_side,
            "swept_high": prev.high if buy_side else None,
            "swept_low": prev.low if sell_side else None
        }
