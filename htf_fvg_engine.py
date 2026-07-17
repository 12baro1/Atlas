"""
htf_fvg_engine.py
Atlas SMC Engine
"""

class HTFFVGEngine:

    def detect(self, h4_fvg, daily_fvg):

        result = {
            "valid": False,
            "timeframe": None,
            "zone": None
        }

        if daily_fvg:
            result["valid"] = True
            result["timeframe"] = "1D"
            result["zone"] = daily_fvg[-1]
            return result

        if h4_fvg:
            result["valid"] = True
            result["timeframe"] = "4H"
            result["zone"] = h4_fvg[-1]

        return result
