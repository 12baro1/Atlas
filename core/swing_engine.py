from atr import atr

class Swing:

    def __init__(self,index,price,kind):
        self.index=index
        self.price=price
        self.kind=kind

def detect(candles,multiplier=1.5):

    if len(candles)<30:
        return []

    average_atr=atr(candles)

    swings=[]

    direction=None
    extreme=candles[0]
    extreme_index=0

    for i,candle in enumerate(candles):

        if direction is None:

            if candle.close>extreme.close:
                direction="UP"

            elif candle.close<extreme.close:
                direction="DOWN"

            extreme=candle
            extreme_index=i
            continue

        if direction=="UP":

            if candle.high>extreme.high:
                extreme=candle
                extreme_index=i

            elif extreme.high-candle.low>=average_atr*multiplier:

                swings.append(
                    Swing(
                        extreme_index,
                        extreme.high,
                        "HIGH"
                    )
                )

                direction="DOWN"
                extreme=candle
                extreme_index=i

        elif direction=="DOWN":

            if candle.low<extreme.low:
                extreme=candle
                extreme_index=i

            elif candle.high-extreme.low>=average_atr*multiplier:

                swings.append(
                    Swing(
                        extreme_index,
                        extreme.low,
                        "LOW"
                    )
                )

                direction="UP"
                extreme=candle
                extreme_index=i

    return swings
