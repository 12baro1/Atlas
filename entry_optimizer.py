"""Evidence-driven entry placement for Atlas.

Primary 4H/weekly direction remains authoritative. Secondary engines influence
where inside an already valid POI Atlas enters; they do not manufacture a setup.
"""
import math


class EntryOptimizer:
    """Blend independent evidence into a price inside the selected POI."""

    def _number(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if math.isfinite(value) and value > 0 else None

    def _direction(self, value):
        value = str(value or "").upper()
        if value in {"LONG", "BULLISH"}:
            return "LONG"
        if value in {"SHORT", "BEARISH"}:
            return "SHORT"
        return "NONE"

    def _add_level(self, levels, value, weight, source, low, high):
        price = self._number(value)
        if price is not None and low <= price <= high:
            levels.append((price, max(0.0, float(weight)), source))

    def optimize(
        self, entry, current_price=None, trend=None, liquidity_sweep=None,
        ote=None, market_phase=None, market_regime=None, htf_orderblock=None,
        htf_fvg=None, smt=None, unicorn=None, cisd=None, volume_profile=None,
        institutional=None, orderbook=None,
    ):
        entry = entry if isinstance(entry, dict) else {}
        direction = str(entry.get("direction", "NONE")).upper()
        zone = entry.get("poi_zone") if isinstance(entry.get("poi_zone"), dict) else {}
        try:
            low, high = float(zone.get("low")), float(zone.get("high"))
        except (TypeError, ValueError, OverflowError):
            return {"applied": False, "reason": "POI zone unavailable", "evidence": []}
        if not entry.get("valid") or direction not in {"LONG", "SHORT"} or not (0 < low < high):
            return {"applied": False, "reason": "Invalid direction or POI", "evidence": []}
        original = self._number(entry.get("entry"))
        current = self._number(current_price)
        stop = self._number(entry.get("stop_loss"))
        if original is None or stop is None:
            return {"applied": False, "reason": "Entry/stop unavailable", "evidence": []}

        # Position is measured from the favorable edge: low for LONG, high for SHORT.
        def to_position(price):
            raw = (price - low) / (high - low)
            return raw if direction == "LONG" else 1.0 - raw

        def from_position(position):
            raw = low + (high - low) * position
            return raw if direction == "LONG" else high - (high - low) * position

        aligned = "BULLISH" if direction == "LONG" else "BEARISH"
        weighted_positions = [(0.50, 2.0, "poi_midpoint")]
        evidence = []

        def add_bias(name, module, weight=1.0):
            if not isinstance(module, dict) or not module.get("active"):
                return
            raw = module.get("direction") or (module.get("best") or {}).get("direction")
            side = self._direction(raw)
            if side == "NONE":
                return
            position = 0.62 if side == direction else 0.24
            confidence = module.get("confidence", (module.get("best") or {}).get("confidence", 55))
            try:
                confidence = max(0.0, min(100.0, float(confidence)))
            except (TypeError, ValueError, OverflowError):
                confidence = 55.0
            strength = weight * (0.5 + confidence / 100.0)
            weighted_positions.append((position, strength, name))
            evidence.append({"source": name, "bias": "ALIGNED" if side == direction else "OPPOSED", "weight": round(strength, 3)})

        trend_side = self._direction((trend or {}).get("trend"))
        if trend_side != "NONE":
            aligned_trend = trend_side == direction
            weighted_positions.append((0.62 if aligned_trend else 0.22, 1.5, "trend"))
            evidence.append({"source": "trend", "bias": "ALIGNED" if aligned_trend else "OPPOSED", "weight": 1.5})

        sweep = liquidity_sweep if isinstance(liquidity_sweep, dict) else {}
        if sweep.get("is_sweep"):
            expected = bool(sweep.get("sell_side")) if direction == "LONG" else bool(sweep.get("buy_side"))
            opposing = bool(sweep.get("buy_side")) if direction == "LONG" else bool(sweep.get("sell_side"))
            post = sweep.get("post_structure") or {}
            post_aligned = bool(post.get("confirmed")) and post.get("direction") == aligned
            if expected and post_aligned:
                weighted_positions.append((0.60, 2.0, "confirmed_sweep"))
                weighted_levels = []
                self._add_level(weighted_levels, sweep.get("sweep_level"), 2.0, "sweep_level", low, high)
                if weighted_levels:
                    weighted_positions.append((to_position(weighted_levels[0][0]), 2.0, "sweep_retest_level"))
                evidence.append({"source": "liquidity_sweep", "bias": "CONFIRMED", "weight": 2.0})
            elif opposing or not expected:
                weighted_positions.append((0.18, 1.8, "sweep_counterpressure"))
                evidence.append({"source": "liquidity_sweep", "bias": "COUNTERPRESSURE", "weight": 1.8})

        add_bias("smt", smt, 1.1)
        add_bias("unicorn", unicorn, 1.3)
        add_bias("cisd", cisd, 1.2)
        add_bias("institutional_flow", institutional, 1.0)

        phase_name = str((market_phase or {}).get("phase", "")).strip().lower()
        sweep_confirmed = bool(
            sweep.get("is_sweep")
            and (sweep.get("post_structure") or {}).get("confirmed")
            and (sweep.get("post_structure") or {}).get("direction") == aligned
        )
        if phase_name == "manipulation" and not sweep_confirmed:
            weighted_positions.append((0.14, 2.0, "manipulation_phase"))
            evidence.append({"source": "market_phase", "bias": "MANIPULATION_RISK", "weight": 2.0})
        elif phase_name == "distribution" and direction == "LONG":
            weighted_positions.append((0.20, 1.2, "distribution_phase"))
            evidence.append({"source": "market_phase", "bias": "COUNTERPRESSURE", "weight": 1.2})
        elif phase_name == "accumulation" and direction == "SHORT":
            weighted_positions.append((0.20, 1.2, "accumulation_phase"))
            evidence.append({"source": "market_phase", "bias": "COUNTERPRESSURE", "weight": 1.2})

        regime_bias = self._direction((market_regime or {}).get("directional_bias"))
        if regime_bias != "NONE":
            regime_aligned = regime_bias == direction
            weighted_positions.append((0.60 if regime_aligned else 0.18, 1.3, "market_regime"))
            evidence.append({"source": "market_regime", "bias": "ALIGNED" if regime_aligned else "OPPOSED", "weight": 1.3})

        # Use actionable prices only when they lie inside the selected POI.
        weighted_levels = []
        if isinstance(ote, dict):
            self._add_level(weighted_levels, ote.get("fib62"), 1.3, "ote_62", low, high)
            self._add_level(weighted_levels, ote.get("fib79"), 1.0, "ote_79", low, high)
        vp = volume_profile if isinstance(volume_profile, dict) else {}
        vp_best = vp.get("best") if isinstance(vp.get("best"), dict) else vp
        if vp_best.get("active"):
            self._add_level(weighted_levels, vp_best.get("poc"), 1.5, "volume_poc", low, high)
            for level in (vp_best.get("hvn") or [])[:3]:
                self._add_level(weighted_levels, level, 0.8, "volume_hvn", low, high)
        inst = institutional if isinstance(institutional, dict) else {}
        self._add_level(weighted_levels, inst.get("vwap"), 1.0, "institutional_vwap", low, high)
        self._add_level(weighted_levels, inst.get("anchored_vwap"), 1.2, "anchored_vwap", low, high)

        for name, module in (("htf_orderblock", htf_orderblock), ("htf_fvg", htf_fvg)):
            if not isinstance(module, dict):
                continue
            candidate = module.get("best") if isinstance(module.get("best"), dict) else module
            candidate_zone = candidate.get("zone") if isinstance(candidate.get("zone"), dict) else candidate
            try:
                center = (float(candidate_zone.get("low")) + float(candidate_zone.get("high"))) / 2
            except (TypeError, ValueError, OverflowError):
                continue
            self._add_level(weighted_levels, center, 1.3, name, low, high)

        best_unicorn = (unicorn or {}).get("best") if isinstance(unicorn, dict) else None
        if isinstance(best_unicorn, dict) and isinstance(best_unicorn.get("zone"), dict):
            z = best_unicorn["zone"]
            try:
                center = (float(z["low"]) + float(z["high"])) / 2
            except (TypeError, KeyError, ValueError, TypeError):
                center = None
            self._add_level(weighted_levels, center, 1.8, "unicorn_zone", low, high)

        book = orderbook if isinstance(orderbook, dict) else {}
        if book.get("active"):
            candidate = book.get("best_bid") if direction == "LONG" else book.get("best_ask")
            self._add_level(weighted_levels, candidate, 1.5 if book.get("supportive") else 0.5, "orderbook_edge", low, high)
            if book.get("opposing"):
                weighted_positions.append((0.16, 1.6, "orderbook_counterpressure"))
                evidence.append({"source": "orderbook", "bias": "COUNTERPRESSURE", "weight": 1.6})
            elif book.get("supportive"):
                weighted_positions.append((0.58, 1.0, "orderbook_support"))
                evidence.append({"source": "orderbook", "bias": "SUPPORTIVE", "weight": 1.0})

        for price, weight, source in weighted_levels:
            weighted_positions.append((to_position(price), weight, source))
            evidence.append({"source": source, "price": round(price, 10), "weight": weight})

        total_weight = sum(weight for _, weight, _ in weighted_positions)
        position = sum(value * weight for value, weight, _ in weighted_positions) / max(total_weight, 1e-9)
        position = max(0.12, min(0.88, position))
        optimized = from_position(position)

        # Never turn an unfilled pullback LIMIT into a market chase.
        entry_type = str(entry.get("entry_type") or "").upper()
        if current is not None:
            if direction == "LONG" and optimized >= current:
                optimized = from_position(0.12)
            elif direction == "SHORT" and optimized <= current:
                optimized = from_position(0.12)

        if (direction == "LONG" and stop >= optimized) or (direction == "SHORT" and stop <= optimized):
            return {"applied": False, "reason": "Optimized entry violates structural stop", "evidence": evidence}

        if entry_type == "LIMIT" and current is not None:
            if (direction == "LONG" and optimized >= current) or (direction == "SHORT" and optimized <= current):
                return {"applied": False, "reason": "Optimized LIMIT is not on pullback side", "evidence": evidence}

        entry["entry"] = optimized
        entry["entry_optimizer"] = {
            "applied": True,
            "original_entry": original,
            "optimized_entry": optimized,
            "position_in_poi": round(position, 4),
            "evidence": evidence,
            "method": "weighted_secondary_engine_evidence",
        }
        entry.setdefault("checks", []).append("Entry price optimized with secondary engine evidence")
        return entry["entry_optimizer"]
