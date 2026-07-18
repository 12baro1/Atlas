"""
risk_engine.py
Atlas Risk Engine v4
"""

from core.analysis_utils import clamp

class RiskEngine:

    def calculate(self, entry, stop_loss, dynamic_tp=None, volume_profile=None):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return None

        account_balance = 1000.0
        risk_percent = 1.0

        capital_at_risk = account_balance * (risk_percent / 100)
        position_size = capital_at_risk / risk

        side = "LONG" if entry > stop_loss else "SHORT"
        vp_factor = self._volume_profile_position_factor(volume_profile, side=side)
        adjusted_position_size = position_size * vp_factor

        tp1 = None
        tp2 = None
        tp3 = None
        rr = None

        if dynamic_tp is not None:

            tp1 = dynamic_tp.get("tp1")
            tp2 = dynamic_tp.get("tp2")
            tp3 = dynamic_tp.get("tp3")

            if tp3 is not None:
                rr = round(abs(tp3 - entry) / risk, 2)

        return {

            "side": side,

            "entry": round(entry, 8),

            "stop_loss": round(stop_loss, 8),

            "risk": round(risk, 8),

            "capital_at_risk": round(capital_at_risk, 2),

            "position_size": round(adjusted_position_size, 4),

            "position_size_raw": round(position_size, 4),

            "volume_profile_factor": round(vp_factor, 4),

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "rr": rr

        }

    def _volume_profile_position_factor(self, volume_profile, side):
        """Volume profile güveni ve yön uyumuna göre pozisyon boyut çarpanı döndürür."""
        if not volume_profile or not volume_profile.get("active"):
            return 1.0

        vp_direction = volume_profile.get("direction", "NONE")
        vp_confidence = volume_profile.get("confidence", 0)
        vp_state = volume_profile.get("state", "NONE")

        direction_match = (
            (side == "LONG" and vp_direction == "BULLISH")
            or (side == "SHORT" and vp_direction == "BEARISH")
        )

        if direction_match:
            state_bonus = 0.05 if (
                (side == "LONG" and vp_state in ["DISCOUNT", "VALUE_LOW", "BELOW_POC"])
                or (side == "SHORT" and vp_state in ["PREMIUM", "VALUE_HIGH", "ABOVE_POC"])
            ) else 0.0

            return clamp(1.0 + (vp_confidence / 450) + state_bonus, 1.0, 1.25)

        state_penalty = 0.05 if vp_state not in ["NONE", ""] else 0.0
        return clamp(1.0 - (vp_confidence / 300) - state_penalty, 0.65, 1.0)
