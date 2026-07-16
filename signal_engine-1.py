"""
signal_engine.py
Atlas SMC Engine
"""

class SignalEngine:

    def generate(self, analysis):

        score = 0
        reasons = []

        if analysis["structure"]:
            last = analysis["structure"][-1]

            if last["label"] in ["HH", "HL"]:
                score += 25
                reasons.append("Bullish Structure")

            elif last["label"] in ["LL", "LH"]:
                score -= 25
                reasons.append("Bearish Structure")

        score += min(len(analysis["liquidity"]) * 2, 20)
        score += min(len(analysis["orderblocks"]) * 3, 20)
        score += min(len(analysis["fvg"]), 15)

        if score >= 45:
            signal = "LONG"

        elif score <= -20:
            signal = "SHORT"

        else:
            signal = "NONE"

        return {
            "signal": signal,
            "score": score,
            "reasons": reasons
        }
