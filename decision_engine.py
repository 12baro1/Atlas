"""
decision_engine.py
Atlas Decision Engine v1
"""


class DecisionEngine:
    """Sinyal, confluence, risk ve CISD çıktılarını aksiyon kararına dönüştürür."""

    def decide(self, signal, confluence, entry, risk, cisd):
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

        if signal_dir in ["LONG", "SHORT"] and confidence >= 75 and score >= 70 and entry_valid and risk_valid:
            if cisd_active and cisd_match:
                action = signal_dir
                reason = "Signal, confluence and CISD are aligned"
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
        }
