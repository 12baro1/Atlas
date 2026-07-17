"""
premium_discount_engine.py
Atlas SMC Engine
"""

class PremiumDiscountEngine:

    def calculate(self, swing_high, swing_low, price):

        if swing_high <= swing_low:
            return {
                "valid": False,
                "premium": False,
                "discount": False,
                "equilibrium": None,
                "premium_zone": None,
                "discount_zone": None
            }

        eq = (swing_high + swing_low) / 2

        premium = price > eq
        discount = price < eq

        return {
            "valid": premium or discount,
            "equilibrium": eq,
            "premium": premium,
            "discount": discount,
            "premium_zone": (eq, swing_high),
            "discount_zone": (swing_low, eq)
        }
