"""
premium_discount_engine.py
Atlas SMC Engine
"""

class PremiumDiscountEngine:
    """
    Premium / Discount Zone (v1)
    """

    def calculate(self, swing_high, swing_low, price):

        if swing_high <= swing_low:
            return {
                "premium": False,
                "discount": False,
                "equilibrium": None
            }

        eq = (swing_high + swing_low) / 2

        return {
            "equilibrium": eq,
            "premium": price > eq,
            "discount": price < eq,
            "premium_zone": (eq, swing_high),
            "discount_zone": (swing_low, eq)
        }
