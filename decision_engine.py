"""
decision_engine.py
Atlas Decision Engine v1
"""


class DecisionEngine:
    """Sinyal, confluence, risk ve CISD çıktılarını aksiyon kararına dönüştürür."""

    def decide(self, signal, confluence, entry, risk, cisd, volume_profile=None):
        action = "WAIT"
        reason = "No qualified setup"

        signal_dir = signal.get("signal", "WAIT")
        confidence = signal.get("confidence", 0)
        score = confluence.get("score", 0)
        entry_valid = entry.get("valid", False)
        risk_valid = risk is not None

        cisd_active = cisd.get("active", False)
        cisd_dir = cisd.get("direction", "NONE")
        cisd_match = (
            (signal_dir == "LONG" and cisd_dir == "BULLISH")
            or (signal_dir == "SHORT" and cisd_dir == "BEARISH")
        )

        vp_direction = (volume_profile or {}).get("direction", "NONE")
        vp_active = bool((volume_profile or {}).get("active"))
        vp_match = (
            (signal_dir == "LONG" and vp_direction == "BULLISH")
            or (signal_dir == "SHORT" and vp_direction == "BEARISH")
        )

        if signal_dir in ["LONG", "SHORT"] and confidence >= 75 and score >= 70 and entry_valid and risk_valid:
            if cisd_active and cisd_match:
                if vp_active and not vp_match:
                    action = "WAIT"
                    reason = "Volume profile direction mismatch"
                else:
                    action = signal_dir
                    reason = "Signal, confluence, CISD and volume profile are aligned"
            elif not cisd_active:
                action = signal_dir
                reason = "Signal qualified without CISD trigger"
            else:
                action = "WAIT"
                reason = "CISD direction mismatch"

        return {
            "action": action,
            "reason": reason,
            "signal": signal_dir,
            "confidence": confidence,
            "confluence_score": score,
            "entry_valid": entry_valid,
            "risk_valid": risk_valid,
            "cisd_active": cisd_active,
            "cisd_direction": cisd_dir,
            "cisd_match": cisd_match,
            "volume_profile_active": vp_active,
            "volume_profile_direction": vp_direction,
            "volume_profile_match": vp_match,
        }
