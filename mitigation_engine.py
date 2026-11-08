"""
mitigation_engine.py
Atlas SMC Engine
"""

class MitigationEngine:

    def detect(self, candles, orderblocks):

        mitigated = []

        for block in orderblocks:

            touched = False

            # The displacement/BOS candle belongs to block formation, not
            # to a later retest. Only candles after the confirmed break can
            # mitigate the newly-created order block.
            try:
                formed_at = int(block.get("break_index", block["index"]))
            except (TypeError, ValueError, OverflowError):
                formed_at = int(block["index"])
            for candle in candles[formed_at + 1:]:

                if candle.high >= block["low"] and candle.low <= block["high"]:
                    touched = True
                    break

            block["mitigated"] = touched
            mitigated.append(block)

        return mitigated
