"""
risk_engine.py
Atlas Risk Engine v4
"""

from core.analysis_utils import clamp
from config import Config

class RiskEngine:

    def calculate(self, entry, stop_loss, dynamic_tp=None, volume_profile=None, institutional=None):

        if entry is None or stop_loss is None:
            return None

        risk = abs(entry - stop_loss)

        if risk <= 0:
            return None

        side = "LONG" if entry > stop_loss else "SHORT"
        vp_factor = self._volume_profile_position_factor(volume_profile, side=side)
        institutional_factor = self._institutional_position_factor(institutional, side=side)

        account_balance = float(getattr(Config, "INITIAL_BALANCE", 1000.0))
        base_risk_percent = float(getattr(Config, "RISK_PERCENT", 1.0))
        round_trip_cost_rate = float(getattr(Config, "ROUND_TRIP_COST_RATE", 0.0012))
        minimum_rr = float(getattr(Config, "MINIMUM_RR", 2.0))

        tp1 = None
        tp2 = None
        tp3 = None
        rr = None
        net_rr = None

        if dynamic_tp is not None:

            tp1 = dynamic_tp.get("tp1")
            tp2 = dynamic_tp.get("tp2")
            tp3 = dynamic_tp.get("tp3")

            if tp3 is not None:
                rr = round(abs(tp3 - entry) / risk, 2)

                gross_reward = abs(tp3 - entry)
                transaction_cost = entry * round_trip_cost_rate
                net_reward = max(0.0, gross_reward - transaction_cost)
                net_rr = round(net_reward / risk, 2)

        risk_reduction_factor = 1.0
        if net_rr is not None and minimum_rr > 0 and net_rr < minimum_rr:
            risk_reduction_factor = clamp(net_rr / minimum_rr, 0.35, 1.0)

        effective_risk_percent = max(0.0, base_risk_percent * risk_reduction_factor)

        target_capital_at_risk = account_balance * (effective_risk_percent / 100)
        position_size = target_capital_at_risk / risk

        raw_sizing_factor = vp_factor * institutional_factor
        capped_sizing_factor = clamp(raw_sizing_factor, 0.65, 1.0)
        adjusted_position_size = position_size * capped_sizing_factor
        effective_capital_at_risk = adjusted_position_size * risk

        return {

            "side": side,

            "entry": round(entry, 8),

            "stop_loss": round(stop_loss, 8),

            "risk": round(risk, 8),

            "capital_at_risk": round(effective_capital_at_risk, 2),

            "capital_at_risk_target": round(target_capital_at_risk, 2),

            "risk_percent": round(effective_risk_percent, 4),

            "risk_percent_base": round(base_risk_percent, 4),

            "position_size": round(adjusted_position_size, 4),

            "position_size_raw": round(position_size, 4),

            "volume_profile_factor": round(vp_factor, 4),

            "institutional_factor": round(institutional_factor, 4),

            "sizing_factor": round(capped_sizing_factor, 4),

            "sizing_factor_raw": round(raw_sizing_factor, 4),

            "portfolio_risk": (institutional or {}).get("portfolio_risk", {}),

            "adaptive_position_sizing": (institutional or {}).get("adaptive_position_sizing", {}),

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "rr": rr,

            "net_rr": net_rr,

            "round_trip_cost_rate": round_trip_cost_rate,

            "minimum_rr": minimum_rr,

            "risk_reduction_factor": round(risk_reduction_factor, 4),

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

    def _institutional_position_factor(self, institutional, side):
        """Kurumsal akış ve risk koşullarına göre pozisyon boyutunu ayarlar."""
        if not institutional or not institutional.get("active"):
            return 1.0

        factor = 1.0
        flow_direction = institutional.get("direction", "NONE")
        flow_confidence = institutional.get("confidence", 0)
        execution_score = institutional.get("execution_quality", {}).get("score", 0)
        portfolio_score = institutional.get("portfolio_risk", {}).get("score", 100)
        adaptive_factor = institutional.get("adaptive_position_sizing", {}).get("factor", 1.0)

        if (side == "LONG" and flow_direction == "LONG") or (side == "SHORT" and flow_direction == "SHORT"):
            factor += min(0.12, flow_confidence / 900)
        elif flow_direction in ["LONG", "SHORT"]:
            factor -= min(0.18, flow_confidence / 650)

        factor += (execution_score - 50) / 1000
        factor += (portfolio_score - 50) / 1200
        factor += (adaptive_factor - 1.0) / 2

        return clamp(factor, 0.65, 1.25)
