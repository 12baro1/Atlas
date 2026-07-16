"""
signal_engine.py
Atlas SMC Engine
"""

class SignalEngine:

    def generate(self, analysis):

        mtf = analysis["mtf"]

        if not mtf["valid"]:
            return {
                "signal": "NONE",
                "score": 0,
                "reasons": ["MTF not aligned"]
            }

        if mtf["entry"] == "LONG":
            return {
                "signal": "LONG",
                "score": 100,
                "reasons": [
                    "Weekly aligned",
                    "Daily aligned",
                    "H4 aligned",
                    "LONG setup"
                ]
            }

        if mtf["entry"] == "SHORT":
            return {
                "signal": "SHORT",
                "score": -100,
                "reasons": [
                    "Weekly aligned",
                    "Daily aligned",
                    "H4 aligned",
                    "SHORT setup"
                ]
            }

        return {
            "signal": "NONE",
            "score": 0,
            "reasons": []
        }
