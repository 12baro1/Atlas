"""
signal_engine.py
Atlas SMC Engine
"""

class SignalEngine:
    """
    Signal Engine v1

    Tüm modüllerden gelen verileri birleştirerek
    BUY / SELL / NONE kararı üretir.
    """

    def generate(self, state):

        score = 0
        reasons = []

        if state.bos:
            score += 2
            reasons.append("BOS")

        if state.choch:
            score += 2
            reasons.append("CHoCH")

        if state.orderblock:
            score += 2
            reasons.append("OrderBlock")

        if state.fvg:
            score += 1
            reasons.append("FVG")

        if state.discount:
            score += 1
            reasons.append("Discount Zone")

        if state.premium:
            score -= 1
            reasons.append("Premium Zone")

        state.score = score
        state.confidence = min(max(score * 20, 0), 100)

        if score >= 5:
            state.signal = "BUY"
        elif score <= -2:
            state.signal = "SELL"
        else:
            state.signal = "NONE"

        state.notes = reasons

        return state
