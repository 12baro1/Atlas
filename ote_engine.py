"""4H swing-leg OTE calculation."""


class OTEEngine:

    def detect(self, swing_high, swing_low, current_price, direction):
        try:
            high = float(swing_high)
            low = float(swing_low)
            price = float(current_price)
        except (TypeError, ValueError, OverflowError):
            return {"valid": False, "zone": None, "fib62": None, "fib79": None}

        if high <= low or low <= 0 or price <= 0:
            return {"valid": False, "zone": None, "fib62": None, "fib79": None}

        if direction == "LONG":
            fib62 = high - ((high - low) * 0.62)
            fib79 = high - ((high - low) * 0.79)
            return {
                "valid": fib79 <= price <= fib62,
                "zone": "DISCOUNT",
                "fib62": fib62,
                "fib79": fib79,
            }

        if direction == "SHORT":
            fib62 = low + ((high - low) * 0.62)
            fib79 = low + ((high - low) * 0.79)
            return {
                "valid": fib62 <= price <= fib79,
                "zone": "PREMIUM",
                "fib62": fib62,
                "fib79": fib79,
            }

        return {"valid": False, "zone": None, "fib62": None, "fib79": None}
