class SignalEngine:

    def generate(self, analysis):

        score = 0
        reasons = []

        if analysis["structure"]:
            last = analysis["structure"][-1]

            bullish = last["label"] in ["HH", "HL"]
            bearish = last["label"] in ["LL", "LH"]

            if bullish:
                score += 25
                score += min(len(analysis["liquidity"]) * 2, 20)
                score += min(len(analysis["orderblocks"]) * 3, 20)
                score += min(len(analysis["fvg"]), 15)
                reasons.append("Bullish Structure")

            elif bearish:
                score -= 25
                score -= min(len(analysis["liquidity"]) * 2, 20)
                score -= min(len(analysis["orderblocks"]) * 3, 20)
                score -= min(len(analysis["fvg"]), 15)
                reasons.append("Bearish Structure")

        if score >= 45:
            signal = "LONG"
        elif score <= -45:
            signal = "SHORT"
        else:
            signal = "NONE"

        return {
            "signal": signal,
            "score": score,
            "reasons": reasons
        }
