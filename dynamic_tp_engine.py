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
            "atr": round(atr_snapshot, 8),
        }

    def _collect_targets(self, direction, entry, liquidity, fvg, orderblocks, structure):
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
        minimum_reward = max(risk * minimum_rr, atr_snapshot * minimum_rr)

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
        """Profesyonel SMC kuralı: TP'leri girişten uzaklığa göre kesin sıralar.

        - tp1 her zaman en yakın, tp3 her zaman en uzak hedeftir (asla ters değil).
        - Her TP kendi minimum RR katını (1R/2R/3R) sağlamazsa yerine
          rr_fallback seviyesi konur; böylece SL genişletilse bile TP oranı korunur.
        - Aynı fiyata düşen kopya seviyeler trade yönünde ötelenerek 3 ayrı
          hedef garanti edilir (tp2 == tp3 asla üretilmez).
        """
        candidates = []
        seen = set()
        for price in targets:
            if price is None:
                continue
            reward = abs(price - entry)
            if reward <= 0 or price in seen:
                continue
            seen.add(price)
            candidates.append((reward, price))

        candidates.sort(key=lambda item: item[0])

        levels = []
        used = set()
        floor_atr = max(float(atr_snapshot or 0.0), 0.0)
        for rr_multiple in self.MIN_RR_LEVELS:
            required_reward = max(risk * rr_multiple, floor_atr * rr_multiple)
            picked = None
            for reward, price in candidates:
                if price in used:
                    continue
                if reward >= required_reward:
                    picked = price
                    break
            if picked is None:
                picked = self._fallback_rr_level(entry, max(risk, 1e-12), direction, rr_multiple)
            picked = self._nudge_level(entry, risk, direction, picked, used)
            used.add(picked)
            levels.append(picked)

        levels.sort(key=lambda price: abs(price - entry))
        return levels[0], levels[1], levels[2]

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
