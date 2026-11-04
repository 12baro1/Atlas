"""
dynamic_tp_engine.py
Atlas Dynamic TP Engine
"""

from utils.atr import atr as calculate_atr

class DynamicTPEngine:

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
        allow_rr_fallback=True,
    ):

        if direction not in {"LONG", "SHORT"}:
            return {"tp1": None, "tp2": None, "tp3": None, "reason": "invalid_direction", "sources": []}

        risk = abs(entry - stop_loss) if stop_loss is not None else 0
        if risk <= 0:
            return {"tp1": None, "tp2": None, "tp3": None, "reason": "invalid_risk", "sources": []}

        atr_snapshot = self._resolve_atr(atr_value=atr_value, candles=candles)
        targets = self._collect_targets(direction, entry, liquidity, fvg, orderblocks, structure)

        selected_targets = []
        selected_sources = []
        previous_target = None

        for rr_multiple in self.MIN_RR_LEVELS:
            target, source = self._select_target_for_rr(
                direction=direction,
                entry=entry,
                risk=risk,
                targets=targets,
                minimum_rr=rr_multiple,
                previous_target=previous_target,
                atr_snapshot=atr_snapshot,
            )

            if target is None and not allow_rr_fallback:
                candidate_rr = [
                    round((entry - price if direction == "SHORT" else price - entry) / risk, 4)
                    for price in targets
                    if (entry - price if direction == "SHORT" else price - entry) > 0
                ]
                return {
                    "tp1": None,
                    "tp2": None,
                    "tp3": None,
                    "reason": "no_valid_structural_targets",
                    "sources": selected_sources + ["missing_structural_target"],
                    "synthetic_targets": False,
                    "atr": round(atr_snapshot, 8),
                    "candidate_count": len(targets),
                    "candidate_targets": [round(float(price), 8) for price in targets],
                    "missing_rr_level": rr_multiple,
                    "best_candidate_rr": max(candidate_rr) if candidate_rr else None,
                }
            if target is None:
                target = self._fallback_rr_level(entry, risk, direction, rr_multiple)
                source = "rr_fallback"

            selected_targets.append(target)
            selected_sources.append(source)
            previous_target = target

        tp1, tp2, tp3 = self._order_target_levels(
            direction=direction,
            entry=entry,
            risk=risk,
            targets=selected_targets,
            atr_snapshot=atr_snapshot,
        )

        return {
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "reason": ",".join(selected_sources),
            "sources": selected_sources,
            "synthetic_targets": any(source == "rr_fallback" for source in selected_sources),
            "atr": round(atr_snapshot, 8),
            "candidate_count": len(targets),
            "candidate_targets": [round(float(price), 8) for price in targets],
            "target_rrs": [
                round((entry - price if direction == "SHORT" else price - entry) / risk, 4)
                for price in selected_targets
            ],
        }

    def _collect_targets(self, direction, entry, liquidity, fvg, orderblocks, structure):
        targets = []

        # Targets must be opposing-side liquidity pools. A long seeks BSL;
        # a short seeks SSL. Unknown liquidity types are not treated as targets.
        expected_liquidity = "BUY_SIDE" if direction == "LONG" else "SELL_SIDE"
        for item in liquidity or []:
            if not isinstance(item, dict) or item.get("type") != expected_liquidity:
                continue
            price = self._safe_float(item.get("price"))
            if price is None:
                continue
            if direction == "LONG" and price > entry:
                targets.append(price)
            elif direction == "SHORT" and price < entry:
                targets.append(price)

        # An opposing, still-unfilled imbalance may be used as an objective;
        # filled gaps are already mitigated and must not be recycled as targets.
        expected_fvg = "BEARISH" if direction == "LONG" else "BULLISH"
        for item in fvg or []:
            if not isinstance(item, dict) or item.get("type") != expected_fvg or item.get("filled", False):
                continue
            if direction == "LONG":
                price = self._safe_float(item.get("from"))
                if price is not None and price > entry:
                    targets.append(price)
            else:
                price = self._safe_float(item.get("to"))
                if price is not None and price < entry:
                    targets.append(price)

        # Opposing fresh order blocks are supply targets for longs and demand
        # targets for shorts. Mitigated blocks are excluded.
        expected_ob = "BEARISH" if direction == "LONG" else "BULLISH"
        for item in orderblocks or []:
            if not isinstance(item, dict) or item.get("type") != expected_ob or item.get("mitigated", False):
                continue
            if direction == "LONG":
                price = self._safe_float(item.get("low"))
                if price is not None and price > entry:
                    targets.append(price)
            else:
                price = self._safe_float(item.get("high"))
                if price is not None and price < entry:
                    targets.append(price)

        for item in structure or []:
            label = str(item.get("label", "")).upper()
            price = self._safe_float(item.get("price"))
            if price is None:
                continue

            if direction == "LONG" and label in {"HH", "LH"} and price > entry:
                targets.append(price)
            if direction == "SHORT" and label in {"LL", "HL"} and price < entry:
                targets.append(price)

        if direction == "LONG":
            return sorted(set(targets))
        return sorted(set(targets), reverse=True)

    def _select_target_for_rr(self, direction, entry, risk, targets, minimum_rr, previous_target=None, atr_snapshot=0.0):
        # ATR is a volatility descriptor, not a second RR denominator. Requiring
        # both risk*R and ATR*R can push targets several times farther away than
        # the actual structural risk and suppress otherwise valid liquidity TP.
        minimum_reward = risk * minimum_rr

        for target in targets:
            if previous_target is not None:
                if direction == "LONG" and target <= previous_target:
                    continue
                if direction == "SHORT" and target >= previous_target:
                    continue

            reward = target - entry if direction == "LONG" else entry - target
            if reward <= 0:
                continue

            rr = reward / risk
            if rr >= minimum_rr and reward >= minimum_reward:
                return target, "market_structure"

        return None, None

    def _fallback_rr_level(self, entry, risk, direction, rr_multiple):
        level = entry + (risk * rr_multiple) if direction == "LONG" else entry - (risk * rr_multiple)
        return round(level, 8)

    def _order_target_levels(self, direction, entry, risk, targets, atr_snapshot=0.0):
        """Return the three already-validated structural targets in trade order.

        Do not manufacture, nudge, or ATR-expand targets here. The caller has
        selected each target against its required R multiple; this method only
        normalizes ordering and refuses duplicate/missing levels.
        """
        candidates = []
        for price in targets:
            value = self._safe_float(price)
            if value is None:
                continue
            reward = value - entry if direction == "LONG" else entry - value
            if reward > 0 and value not in candidates:
                candidates.append(value)
        candidates.sort(key=lambda price: abs(price - entry))
        if len(candidates) < 3:
            return None, None, None
        return candidates[0], candidates[1], candidates[2]

    def _nudge_level(self, entry, risk, direction, picked, used):
        """Çakışan seviyeyi trade yönünde basamak basamak öteleyerek benzersiz yapar."""
        step = max(risk * 0.1, 1e-12)
        sign = 1.0 if direction == "LONG" else -1.0
        guard = 0
        while picked in used and guard < 500:
            picked = round(picked + sign * step, 8)
            guard += 1
        return picked

    def _safe_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_atr(self, atr_value=None, candles=None):
        if atr_value is not None:
            try:
                return max(0.0, float(atr_value))
            except (TypeError, ValueError):
                return 0.0

        if candles:
            try:
                return max(0.0, float(calculate_atr(candles, period=14)))
            except Exception:
                return 0.0

        return 0.0
