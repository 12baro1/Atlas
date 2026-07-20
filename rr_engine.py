"""
rr_engine.py
Atlas SMC Engine v3
"""

import math

class RREngine:

    def calculate_rr(self, entry, stop_loss, tp):
        """Tek bir TP seviyesi için yön bazlı RR hesaplar."""
        if entry is None or stop_loss is None or tp is None:
            return None

        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None

        direction = self._resolve_direction(entry, stop_loss)
        if direction == "LONG":
            reward = tp - entry
        elif direction == "SHORT":
            reward = entry - tp
        else:
            return None

        rr = reward / risk
        if not math.isfinite(rr):
            return None

        return round(rr, 2)

    def calculate_breakdown(self, entry, stop_loss, tp1=None, tp2=None, tp3=None, selection_rule="max_rr"):
        """TP1/TP2/TP3 için RR dökümü ve nihai seçimi üretir."""
        if entry is None or stop_loss is None:
            return None

        direction = self._resolve_direction(entry, stop_loss)
        if direction is None:
            return None

        risk = abs(entry - stop_loss)
        if risk <= 0:
            return None

        rr_by_tp = {}
        tp_values = {"tp1": tp1, "tp2": tp2, "tp3": tp3}

        for tp_name, tp_value in tp_values.items():
            rr_value = self.calculate_rr(entry, stop_loss, tp_value)
            if rr_value is not None:
                rr_by_tp[tp_name] = rr_value

        if not rr_by_tp:
            return None

        selected_tp = None
        selected_rr = None

        if selection_rule == "tp3" and rr_by_tp.get("tp3") is not None:
            selected_tp = "tp3"
            selected_rr = rr_by_tp["tp3"]
        elif selection_rule == "tp1" and rr_by_tp.get("tp1") is not None:
            selected_tp = "tp1"
            selected_rr = rr_by_tp["tp1"]
        else:
            selected_tp, selected_rr = max(rr_by_tp.items(), key=lambda item: item[1])

        return {
            "direction": direction,
            "risk": round(risk, 8),
            "rr_by_tp": rr_by_tp,
            "selected_tp": selected_tp,
            "selected_rr": round(selected_rr, 2),
            "selection_rule": selection_rule,
        }

    def evaluate(self, risk):

        if risk is None:
            return None

        rr = risk.get("rr")
        rr_by_tp = risk.get("rr_by_tp") if isinstance(risk, dict) else None
        selected_tp = risk.get("selected_tp") if isinstance(risk, dict) else None
        selection_rule = risk.get("rr_selection_rule") if isinstance(risk, dict) else None

        if rr is None and isinstance(risk, dict):
            breakdown = self.calculate_breakdown(
                risk.get("entry"),
                risk.get("stop_loss"),
                tp1=risk.get("tp1"),
                tp2=risk.get("tp2"),
                tp3=risk.get("tp3"),
                selection_rule=selection_rule or "max_rr",
            )

            if breakdown is not None:
                rr = breakdown["selected_rr"]
                rr_by_tp = breakdown["rr_by_tp"]
                selected_tp = breakdown["selected_tp"]
                selection_rule = breakdown["selection_rule"]

        if rr is not None:
            try:
                rr = round(float(rr), 2)
            except (TypeError, ValueError):
                rr = None

        if rr is None:
            return None

        if rr >= 5:
            stars = "★★★★★"
            quality = "EXCELLENT"
            score = 100

        elif rr >= 4:
            stars = "★★★★☆"
            quality = "VERY GOOD"
            score = 90

        elif rr >= 3:
            stars = "★★★☆☆"
            quality = "GOOD"
            score = 80

        elif rr >= 2:
            stars = "★★☆☆☆"
            quality = "NORMAL"
            score = 65

        elif rr >= 1.5:
            stars = "★☆☆☆☆"
            quality = "WEAK"
            score = 45

        else:
            stars = "☆☆☆☆☆"
            quality = "AVOID"
            score = 20

        return {

            "rr": rr,

            "selected_tp": selected_tp,

            "selected_rr": rr,

            "rr_by_tp": rr_by_tp,

            "rr_selection_rule": selection_rule,

            "score": score,

            "quality": quality,

            "stars": stars,

            "entry": risk.get("entry"),

            "stop_loss": risk.get("stop_loss"),

            "tp1": risk.get("tp1"),

            "tp2": risk.get("tp2"),

            "tp3": risk.get("tp3"),

            "position_size": risk.get("position_size"),

            "capital_at_risk": risk.get("capital_at_risk")

        }

    def _resolve_direction(self, entry, stop_loss):
        if entry is None or stop_loss is None:
            return None

        if entry > stop_loss:
            return "LONG"
        if entry < stop_loss:
            return "SHORT"
        return None
