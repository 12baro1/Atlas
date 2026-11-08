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
        institutional=None, orderbook=None, correlation=None, breaker=None,
        trendline_sweep=None, ifvg=None, eqh_eql=None, internal_structure=None,
        external_structure=None, current_index=None,
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
        stronger_confirmation_reasons = []

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
            quality_source = module.get("cvd") if isinstance(module.get("cvd"), dict) else module
            is_proxy = bool(quality_source.get("is_proxy")) or "proxy" in str(quality_source.get("source", "")).lower()
            quality_factor = 0.40 if is_proxy else 1.0
            strength = weight * (0.5 + confidence / 100.0) * quality_factor
            weighted_positions.append((position, strength, name))
            evidence.append({
                "source": name, "bias": "ALIGNED" if side == direction else "OPPOSED",
                "weight": round(strength, 3),
                "data_quality": "PROXY" if is_proxy else "LIVE_OR_NATIVE",
                "quality_factor": quality_factor,
            })
            if side != direction and confidence >= 70:
                stronger_confirmation_reasons.append(f"{name}_opposes")

        # Trend, MTF yönünün/structure özetinin türevi olduğundan bağımsız oy sayılmaz.

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
                stronger_confirmation_reasons.append("liquidity_sweep_counterpressure")

        add_bias("smt", smt, 1.1)
        add_bias("unicorn", unicorn, 1.3)
        add_bias("cisd", cisd, 1.2)
        add_bias("institutional_flow", institutional, 1.0)

        correlation_state = correlation if isinstance(correlation, dict) else {}
        if correlation_state.get("active"):
            try:
                pressure = float(correlation_state.get("counterpressure_score", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                pressure = 0.0
            if correlation_state.get("counterpressure"):
                weight = 1.0 + max(0.0, min(1.0, pressure))
                weighted_positions.append((0.16, weight, "correlation_counterpressure"))
                evidence.append({"source": "correlation", "bias": "COUNTERPRESSURE", "weight": round(weight, 3)})
                stronger_confirmation_reasons.append("correlation_counterpressure")
            elif correlation_state.get("supportive"):
                weighted_positions.append((0.60, 0.9, "correlation_support"))
                evidence.append({"source": "correlation", "bias": "SUPPORTIVE", "weight": 0.9})

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

        # All remaining structural motors contribute evidence and/or a price
        # level inside the already selected POI. None of these motors vetoes it.
        weighted_levels = []

        trendline = trendline_sweep if isinstance(trendline_sweep, dict) else {}
        if trendline.get("active"):
            sweep_side = str(trendline.get("direction", "")).upper()
            sweep_direction = "LONG" if sweep_side == "SELL_SIDE" else "SHORT" if sweep_side == "BUY_SIDE" else "NONE"
            if sweep_direction != "NONE":
                aligned_sweep = sweep_direction == direction
                weighted_positions.append((0.62 if aligned_sweep else 0.16, 1.4, "trendline_sweep"))
                evidence.append({"source": "trendline_sweep", "bias": "ALIGNED" if aligned_sweep else "COUNTERPRESSURE", "weight": 1.4})

        recent_ifvg = []
        for gap in (ifvg or []):
            if not isinstance(gap, dict) or not gap.get("inverted"):
                continue
            try:
                index = int(gap.get("index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if current_index is not None and index < int(current_index) - 48:
                continue
            recent_ifvg.append(gap)
        for gap in recent_ifvg[-4:]:
            original_side = str(gap.get("type", "")).upper()
            effective_side = "SHORT" if original_side == "BULLISH" else "LONG" if original_side == "BEARISH" else "NONE"
            if effective_side == "NONE":
                continue
            aligned_gap = effective_side == direction
            weighted_positions.append((0.62 if aligned_gap else 0.16, 1.2, "ifvg"))
            evidence.append({"source": "ifvg", "bias": "ALIGNED" if aligned_gap else "COUNTERPRESSURE", "weight": 1.2})
            try:
                zone_low, zone_high = sorted((float(gap.get("from")), float(gap.get("to"))))
                self._add_level(weighted_levels, (zone_low + zone_high) / 2, 1.2, "ifvg_zone", low, high)
            except (TypeError, ValueError, OverflowError):
                pass

        equal_levels = eqh_eql if isinstance(eqh_eql, dict) else {}
        equal_key = "eql" if direction == "LONG" else "eqh"
        for level in (equal_levels.get(equal_key) or [])[:3]:
            if not isinstance(level, dict):
                continue
            indices = level.get("indices") or []
            if current_index is not None and indices and max(indices) < int(current_index) - 48:
                continue
            self._add_level(weighted_levels, level.get("price"), 1.0, f"equal_{equal_key}", low, high)
            evidence.append({"source": f"equal_{equal_key}", "bias": "SUPPORTIVE", "weight": 1.0})

        recent_internal = [
            item for item in (internal_structure or [])
            if isinstance(item, dict)
            and (current_index is None or int(item.get("index", current_index)) >= int(current_index) - 48)
        ][-8:]
        internal_labels = [str(item.get("label", "")).upper() for item in recent_internal]
        internal_bull = sum(label in {"HH", "HL"} for label in internal_labels)
        internal_bear = sum(label in {"LH", "LL"} for label in internal_labels)
        internal_side = "LONG" if internal_bull > internal_bear else "SHORT" if internal_bear > internal_bull else "NONE"
        if internal_side != "NONE":
            aligned_internal = internal_side == direction
            weighted_positions.append((0.60 if aligned_internal else 0.18, 1.1, "internal_structure"))
            evidence.append({"source": "internal_structure", "bias": "ALIGNED" if aligned_internal else "COUNTERPRESSURE", "weight": 1.1})

        recent_external = [
            item for item in (external_structure or [])
            if isinstance(item, dict)
            and (item.get("bos") or item.get("choch"))
            and str(item.get("direction", "")).upper() in {"BULLISH", "BEARISH"}
        ]
        if current_index is not None:
            recent_external = [
                item for item in recent_external
                if int(item.get("index", current_index)) >= int(current_index) - 64
            ]
        if recent_external:
            event = recent_external[-1]
            external_side = "LONG" if str(event["direction"]).upper() == "BULLISH" else "SHORT"
            aligned_external = external_side == direction
            weighted_positions.append((0.62 if aligned_external else 0.16, 1.4, "external_structure"))
            evidence.append({"source": "external_structure", "bias": "ALIGNED" if aligned_external else "COUNTERPRESSURE", "weight": 1.4})

        recent_breakers = []
        for block in (breaker or []):
            if not isinstance(block, dict) or not block.get("breaker"):
                continue
            try:
                index = int(block.get("break_index", block.get("index", -1)))
            except (TypeError, ValueError, OverflowError):
                continue
            if current_index is not None and index < int(current_index) - 48:
                continue
            recent_breakers.append(block)
        for block in recent_breakers[-3:]:
            block_side = "LONG" if str(block.get("type", "")).upper() == "BULLISH" else "SHORT"
            aligned_breaker = block_side == direction
            weighted_positions.append((0.62 if aligned_breaker else 0.16, 1.2, "breaker"))
            evidence.append({"source": "breaker", "bias": "ALIGNED" if aligned_breaker else "COUNTERPRESSURE", "weight": 1.2})
            try:
                self._add_level(weighted_levels, (float(block.get("low")) + float(block.get("high"))) / 2, 1.2, "breaker_zone", low, high)
            except (TypeError, ValueError, OverflowError):
                pass

        # Use actionable prices only when they lie inside the selected POI.
        if isinstance(ote, dict):
            self._add_level(weighted_levels, ote.get("fib62"), 1.3, "ote_62", low, high)
            self._add_level(weighted_levels, ote.get("fib79"), 1.0, "ote_79", low, high)
        vp = volume_profile if isinstance(volume_profile, dict) else {}
        vp_best = vp.get("best") if isinstance(vp.get("best"), dict) else vp
        if vp_best.get("active"):
            try:
                vp_confidence = float(vp_best.get("confidence", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                vp_confidence = 0.0
            vp_direction = self._direction(vp_best.get("direction"))
            if vp_confidence < 45 or (vp_direction not in {"NONE", direction} and vp_confidence >= 55):
                stronger_confirmation_reasons.append("weak_or_opposing_volume_profile")
                weighted_positions.append((0.18, 1.5, "volume_profile_counterpressure"))
            vp_is_proxy = bool(vp_best.get("is_proxy")) or "proxy" in str(vp_best.get("source", "")).lower()
            vp_quality = 0.40 if vp_is_proxy else 1.0
            self._add_level(weighted_levels, vp_best.get("poc"), 1.5 * vp_quality, "volume_poc", low, high)
            for level in (vp_best.get("hvn") or [])[:3]:
                self._add_level(weighted_levels, level, 0.8 * vp_quality, "volume_hvn", low, high)
            evidence.append({
                "source": "volume_profile", "bias": "CONTEXT",
                "data_quality": "PROXY" if vp_is_proxy else "LIVE_OR_NATIVE",
                "quality_factor": vp_quality,
            })
        inst = institutional if isinstance(institutional, dict) else {}
        volume_delta = inst.get("volume_delta") if isinstance(inst.get("volume_delta"), dict) else {}
        try:
            volume_imbalance = float(volume_delta.get("imbalance"))
        except (TypeError, ValueError, OverflowError):
            volume_imbalance = None
        if volume_imbalance is not None:
            delta_side = self._direction(volume_delta.get("direction"))
            delta_proxy = bool(volume_delta.get("is_proxy")) or "proxy" in str(volume_delta.get("source", "")).lower()
            delta_quality = 0.40 if delta_proxy else 1.0
            if abs(volume_imbalance) < 0.08:
                weighted_positions.append((0.28, 1.0 * delta_quality, "weak_volume_delta"))
                evidence.append({"source": "volume_delta", "bias": "WEAK", "imbalance": volume_imbalance, "data_quality": "PROXY" if delta_proxy else "LIVE", "quality_factor": delta_quality})
            elif delta_side not in {"NONE", direction}:
                weighted_positions.append((0.18, 1.3 * delta_quality, "opposing_volume_delta"))
                evidence.append({"source": "volume_delta", "bias": "OPPOSED", "imbalance": volume_imbalance, "data_quality": "PROXY" if delta_proxy else "LIVE", "quality_factor": delta_quality})
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
                stronger_confirmation_reasons.append("orderbook_opposes")
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

        # All secondary motors contribute to the shared entry price. Their
        # disagreement changes the evidence balance and entry location only;
        # it never creates a mandatory confirmation gate.
        aligned_weight = sum(
            float(item.get("weight", 0) or 0)
            for item in evidence
            if item.get("bias") in {"ALIGNED", "SUPPORTIVE", "CONFIRMED"}
        )
        opposing_weight = sum(
            float(item.get("weight", 0) or 0)
            for item in evidence
            if item.get("bias") in {"OPPOSED", "COUNTERPRESSURE", "MANIPULATION_RISK", "WEAK"}
        )
        entry.pop("confirmation_requirements", None)
        entry["confirmation_profile"] = {
            "mode": "EVIDENCE_BALANCE",
            "aligned_weight": round(aligned_weight, 3),
            "opposing_weight": round(opposing_weight, 3),
            "evidence_balance": round(aligned_weight - opposing_weight, 3),
            "counterpressure_reasons": sorted(set(stronger_confirmation_reasons)),
        }
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
