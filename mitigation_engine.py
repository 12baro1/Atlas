"""
mitigation_engine.py
Atlas SMC Engine
"""

class MitigationEngine:

    def detect(self, candles, orderblocks):

        mitigated = []

        for block in orderblocks:

            touched = False

            for candle in candles[block["index"] + 1:]:

                if candle.high >= block["low"] and candle.low <= block["high"]:
                    touched = True
                    break

            block["mitigated"] = touched
            mitigated.append(block)

        return mitigated
