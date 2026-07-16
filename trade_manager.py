"""
trade_manager.py
Atlas SMC Engine
"""

class TradeManager:
    """
    Final trade validation.
    """

    def build(self, signal, entry, confirmation, risk, rr):

        if signal.get("signal") == "NONE":
            return {
                "valid": False,
                "reason": "No signal"
            }

        if not entry.get("valid", False):
            return {
                "valid": False,
                "reason": "Entry rejected"
            }

        if not confirmation.get("confirmed", False):
            return {
                "valid": False,
                "reason": confirmation.get("reason", "Confirmation failed")
            }

        if not risk.get("valid", False):
            return {
                "valid": False,
                "reason": "Risk invalid"
            }

        if not rr.get("valid", False):
            return {
                "valid": False,
                "reason": "Risk/Reward too low"
            }

        return {
            "valid": True,
            "direction": signal["signal"],
            "entry": risk["entry"],
            "stop_loss": risk["sl"],
            "tp1": risk["tp1"],
            "tp2": risk["tp2"],
            "tp3": risk["tp3"],
            "rr": rr["rr"]
        }
