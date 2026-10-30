
def atr(candles, period=14):

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i-1]

        tr = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close)
        )

        trs.append(tr)

    if len(trs) < period:
        return 0

    return sum(trs[-period:]) / period

