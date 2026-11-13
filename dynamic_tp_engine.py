"""
dynamic_tp_engine.py
Atlas Dynamic TP Engine
"""

import math

from utils.atr import atr as calculate_atr
from config import Config


class DynamicTPEngine:
    """Select real, directional market-structure objectives without inventing spacing."""

    MIN_RR_LEVELS = (1.0, 2.0, 3.0)

    def calculate(
        self,
        direction,
        entry,
        stop_loss,
        liquidity,
        fvg,
        orderblocks,
        structure=None,
        candles=None,
        atr_value=None,
        allow_rr_fallback=False,
        exclude_targets_through=None,
    ):
        direction = str(direction or "").upper()
        if direction not in {"LONG", "SHORT"}:
            return self._empty("invalid_direction")
        entry = self._safe_float(entry)
        stop_loss = self._safe_float(stop_loss)
        if entry is None or stop_loss is None or entry <= 0 or stop_loss <= 0:
            return self._empty("invalid_levels")
        if (direction == "LONG" and stop_loss >= entry) or (direction == "SHORT" and stop_loss <= entry):
            return self._empty("stop_on_wrong_side")
        risk = abs(entry - stop_loss)
        if risk <= 0:
            return self._empty("invalid_risk")

        atr_snapshot = self._resolve_atr(atr_value=atr_value, candles=candles)
        raw_targets = self._collect_targets(direction, entry, liquidity, fvg, orderblocks, structure)
        excluded_passed_targets = []
        cutoff = self._safe_float(exclude_targets_through)
        if cutoff is not None and cutoff > 0:
            if direction == "LONG":
                excluded_passed_targets = [price for price in raw_targets if price <= cutoff]
                raw_targets = [price for price in raw_targets if price > cutoff]
            else:
                excluded_passed_targets = [price for price in raw_targets if price >= cutoff]
                raw_targets = [price for price in raw_targets if price < cutoff]

        selected = self.select_structural_targets(
            direction=direction,
            entry=entry,
            risk=risk,
            targets=raw_targets,
            atr_snapshot=atr_snapshot,
        )
        sources = ["market_structure"] * len(selected)
        synthetic = False

        if not selected and allow_rr_fallback:
            selected = [
                self._fallback_rr_level(entry, risk, direction, rr)
                for rr in self.MIN_RR_LEVELS
            ]
            sources = ["rr_fallback"] * len(selected)
            synthetic = True

        if not selected:
            candidate_rrs = [
                self._reward(entry, price, direction) / risk
                for price in raw_targets
                if self._reward(entry, price, direction) > 0
            ]
            best_candidate_rr = max(candidate_rrs) if candidate_rrs else None
            missing_rr_level = next(
                (rr for rr in self.MIN_RR_LEVELS if best_candidate_rr is None or best_candidate_rr < rr),
                None,
            )
            return {
                **self._empty("no_valid_structural_targets"),
                "sources": ["missing_structural_target"],
                "synthetic_targets": False,
                "atr": round(atr_snapshot, 8),
                "candidate_count": len(raw_targets),
                "candidate_targets": [round(price, 8) for price in raw_targets],
                "excluded_passed_targets": [round(price, 8) for price in excluded_passed_targets],
                "target_exclusion_price": round(cutoff, 8) if cutoff is not None and cutoff > 0 else None,
                "missing_rr_level": missing_rr_level,
                "best_candidate_rr": round(best_candidate_rr, 4) if best_candidate_rr is not None else None,
                "minimum_target_separation": self.minimum_target_separation(entry, risk, atr_snapshot),
            }

        selected = selected[:3]
        tp1, tp2, tp3 = self._order_target_levels(direction, entry, risk, selected)
        target_rrs = [round(self._reward(entry, price, direction) / risk, 4) for price in selected]
        best_candidate_rr = (
            max(target_rrs) if synthetic else
            max(
                (self._reward(entry, price, direction) / risk for price in raw_targets),
                default=None,
            )
        )
        selected_best_rr = max(target_rrs, default=None)
        missing_rr_level = next(
            (rr for rr in self.MIN_RR_LEVELS if selected_best_rr is None or selected_best_rr < rr),
            None,
        )
        return {
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "reason": ",".join(sources),
            "sources": sources,
            "synthetic_targets": synthetic,
            "atr": round(atr_snapshot, 8),
            "candidate_count": len(raw_targets),
            "candidate_targets": [round(price, 8) for price in raw_targets],
            "clustered_targets": [round(price, 8) for price in selected],
            "excluded_passed_targets": [round(price, 8) for price in excluded_passed_targets],
            "target_exclusion_price": round(cutoff, 8) if cutoff is not None and cutoff > 0 else None,
            "target_rrs": target_rrs,
            "missing_rr_level": missing_rr_level,
            "best_candidate_rr": round(best_candidate_rr, 4) if best_candidate_rr is not None else None,
            "minimum_target_separation": self.minimum_target_separation(entry, risk, atr_snapshot),
        }

    @staticmethod
    def _empty(reason):
        return {
            "tp1": None, "tp2": None, "tp3": None,
            "reason": reason, "sources": [], "synthetic_targets": False,
        }

    @staticmethod
    def _reward(entry, target, direction):
        return target - entry if direction == "LONG" else entry - target

    def minimum_target_separation(self, entry, risk, atr_snapshot=0.0):
        risk_floor = risk * max(0.0, float(getattr(Config, "MIN_TP_TARGET_SEPARATION_R", 0.35)))
        atr_floor = min(
            atr_snapshot * max(0.0, float(getattr(Config, "MIN_TP_TARGET_SEPARATION_ATR", 0.20))),
            risk * 0.75,
        )
        percent_floor = entry * max(0.0, float(getattr(Config, "MIN_TP_TARGET_SEPARATION_PERCENT", 0.0005)))
        return max(risk_floor, atr_floor, percent_floor, 1e-12)

    def select_structural_targets(self, direction, entry, risk, targets, atr_snapshot=0.0):
        """Return nearest valid objectives, collapsing levels that belong to one price cluster."""
        direction = str(direction or "").upper()
        if direction not in {"LONG", "SHORT"} or risk <= 0:
            return []
        minimum_first_rr = max(0.0, float(getattr(Config, "MIN_TP1_RR", 0.80)))
        min_separation = self.minimum_target_separation(entry, risk, atr_snapshot)
        valid = []
        for raw in targets or []:
            price = self._safe_float(raw)
            if price is None or price <= 0:
                continue
            reward = self._reward(entry, price, direction)
            if reward <= 0 or reward / risk < minimum_first_rr:
                continue
            if not any(abs(price - existing) <= max(entry, price) * 1e-10 for existing in valid):
                valid.append(price)
        valid.sort(reverse=(direction == "SHORT"))
        selected = []
        for price in valid:
            if not selected or abs(price - selected[-1]) >= min_separation:
                selected.append(price)
                if len(selected) == 3:
                    break
        return selected

    def _collect_targets(self, direction, entry, liquidity, fvg, orderblocks, structure):
        targets = []
        expected_liquidity = "BUY_SIDE" if direction == "LONG" else "SELL_SIDE"
        for item in liquidity or []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != expected_liquidity:
                continue
            price = self._safe_float(item.get("price"))
            if price is not None and self._reward(entry, price, direction) > 0:
                targets.append(price)

        expected_fvg = "BEARISH" if direction == "LONG" else "BULLISH"
        for item in fvg or []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != expected_fvg or item.get("filled", False):
                continue
            key = "from" if direction == "LONG" else "to"
            price = self._safe_float(item.get(key))
            if price is not None and self._reward(entry, price, direction) > 0:
                targets.append(price)

        expected_ob = "BEARISH" if direction == "LONG" else "BULLISH"
        for item in orderblocks or []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != expected_ob or item.get("mitigated", False):
                continue
            key = "low" if direction == "LONG" else "high"
            price = self._safe_float(item.get(key))
            if price is not None and self._reward(entry, price, direction) > 0:
                targets.append(price)

        for item in structure or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).upper()
            price = self._safe_float(item.get("price"))
            if price is None:
                continue
            if direction == "LONG" and label in {"HH", "LH"} and price > entry:
                targets.append(price)
            elif direction == "SHORT" and label in {"LL", "HL"} and price < entry:
                targets.append(price)

        return sorted(set(targets), reverse=(direction == "SHORT"))

    def _fallback_rr_level(self, entry, risk, direction, rr_multiple):
        level = entry + risk * rr_multiple if direction == "LONG" else entry - risk * rr_multiple
        return round(level, 8)

    def _order_target_levels(self, direction, entry, risk, targets, atr_snapshot=0.0):
        candidates = [
            price for price in targets
            if self._reward(entry, price, direction) > 0
        ]
        candidates.sort(key=lambda price: abs(price - entry))
        candidates = candidates[:3]
        candidates.extend([None] * (3 - len(candidates)))
        return candidates[0], candidates[1], candidates[2]

    def _safe_float(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def _resolve_atr(self, atr_value=None, candles=None):
        if atr_value is not None:
            value = self._safe_float(atr_value)
            return max(0.0, value) if value is not None else 0.0
        if candles:
            try:
                value = self._safe_float(calculate_atr(candles, period=14))
                return max(0.0, value) if value is not None else 0.0
            except Exception:
                return 0.0
        return 0.0
