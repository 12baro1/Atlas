"""
ote_engine.py
Atlas OTE Engine v1
"""

class OTEEngine:

    def detect(
        self,
        swing_high,
        swing_low,
        current_price,
        direction
    ):

        if direction == "LONG":

            fib62 = swing_high - ((swing_high - swing_low) * 0.62)
            fib79 = swing_high - ((swing_high - swing_low) * 0.79)

            valid = fib79 <= current_price <= fib62

            return {
                "valid": valid,
                "zone": "DISCOUNT",
                "fib62": fib62,
                "fib79": fib79
            }

        elif direction == "SHORT":

            fib62 = swing_low + ((swing_high - swing_low) * 0.62)
            fib79 = swing_low + ((swing_high - swing_low) * 0.79)

            valid = fib62 <= current_price <= fib79

            return {
                "valid": valid,
                "zone": "PREMIUM",
                "fib62": fib62,
                "fib79": fib79
            }

        return {
            "valid": False,
            "zone": None,
            "fib62": None,
            "fib79": None
        }
