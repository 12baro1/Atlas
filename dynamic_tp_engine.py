"""
dynamic_tp_engine.py
Atlas Dynamic TP Engine
"""

class DynamicTPEngine:

    MIN_RR_LEVELS = (1.0, 2.0, 3.0)

    def calculate(
        self,
        direction,
        entry,
        stop_loss,
        liquidity,
        fvg,
        orderblocks
    ):

        if direction not in {"LONG", "SHORT"}:
            return {"tp1": None, "tp2": None, "tp3": None}

        risk = abs(entry - stop_loss) if stop_loss is not None else 0
        if risk <= 0:
            return {"tp1": None, "tp2": None, "tp3": None}

        targets = self._collect_targets(direction, entry, liquidity, fvg, orderblocks)

        selected_targets = []
        previous_target = None

        for rr_multiple in self.MIN_RR_LEVELS:
            target = self._select_target_for_rr(
                direction=direction,
                entry=entry,
                risk=risk,
                targets=targets,
                minimum_rr=rr_multiple,
                previous_target=previous_target,
            )

            if target is None:
                target = self._fallback_rr_level(entry, risk, direction, rr_multiple)

            selected_targets.append(target)
            previous_target = target

        return {
            "tp1": selected_targets[0],
            "tp2": selected_targets[1],
            "tp3": selected_targets[2],
        }

    def _collect_targets(self, direction, entry, liquidity, fvg, orderblocks):
        targets = []

        for item in liquidity or []:
            price = self._safe_float(item.get("price"))
            if price is None:
                continue
            if direction == "LONG" and price > entry:
                targets.append(price)
            elif direction == "SHORT" and price < entry:
                targets.append(price)

        for item in fvg or []:
            if direction == "LONG":
                price = self._safe_float(item.get("to"))
                if price is not None and price > entry:
                    targets.append(price)
            else:
                price = self._safe_float(item.get("from"))
                if price is not None and price < entry:
                    targets.append(price)

        for item in orderblocks or []:
            if direction == "LONG":
                price = self._safe_float(item.get("high"))
                if price is not None and price > entry:
                    targets.append(price)
            else:
                price = self._safe_float(item.get("low"))
                if price is not None and price < entry:
                    targets.append(price)

        if direction == "LONG":
            return sorted(set(targets))
        return sorted(set(targets), reverse=True)

    def _select_target_for_rr(self, direction, entry, risk, targets, minimum_rr, previous_target=None):
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
            if rr >= minimum_rr:
                return target

        return None

    def _fallback_rr_level(self, entry, risk, direction, rr_multiple):
        level = entry + (risk * rr_multiple) if direction == "LONG" else entry - (risk * rr_multiple)
        return round(level, 8)

    def _safe_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
