"""Premium/discount zones derived from a validated swing range."""

import math


class PremiumDiscountEngine:
    @staticmethod
    def _invalid():
        return {
            "valid": False,
            "premium": False,
            "discount": False,
            "equilibrium": None,
            "equilibrium_price": False,
            "premium_zone": None,
            "discount_zone": None,
        }

    def calculate(self, swing_high, swing_low, price):
        try:
            swing_high = float(swing_high)
            swing_low = float(swing_low)
            price = float(price)
        except (TypeError, ValueError, OverflowError):
            return self._invalid()

        if not all(math.isfinite(value) and value > 0 for value in (swing_high, swing_low, price)):
            return self._invalid()
        if swing_high <= swing_low:
            return self._invalid()

        equilibrium = (swing_high + swing_low) / 2.0
        premium = price > equilibrium
        discount = price < equilibrium
        at_equilibrium = math.isclose(
            price, equilibrium, rel_tol=1e-12,
            abs_tol=max(abs(equilibrium) * 1e-12, 1e-12),
        )

        return {
            # Equilibrium is a valid range location, but neither a premium nor
            # discount entry zone; callers must not award either directional bias.
            "valid": premium or discount,
            "premium": premium,
            "discount": discount,
            "equilibrium": equilibrium,
            "equilibrium_price": at_equilibrium,
            "premium_zone": (equilibrium, swing_high),
            "discount_zone": (swing_low, equilibrium),
        }
