"""Candidate-based setup reasoning for Atlas.

Motor outputs are interpreted as scenarios, not votes. The engine creates
independent POI candidates, records the evidence chain, and selects one using
structural validity, target geometry and execution quality.
"""
import math


class SetupReasoningEngine:
    DIRECTIONS = ("LONG", "SHORT")

    @staticmethod
    def _number(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _direction(value):
        raw = str(value or "").strip().upper()
        if raw in {"LONG", "BULLISH", "BUY"}:
            return "LONG"
        if raw in {"SHORT", "BEARISH", "SELL"}:
            return "SHORT"
        return "NONE"

    @staticmethod
    def _bounds(item, source):
        if not isinstance(item, dict):
            return None
        if source in {"FVG", "HTF_FVG"}:
            first, second = item.get("from"), item.get("to")
        else:
            first, second = item.get("low"), item.get("high")
        try:
            low, high = sorted((float(first), float(second)))
        except (TypeError, ValueError, OverflowError):
            return None
        if not (math.isfinite(low) and math.isfinite(high) and 0 < low < high):
            return None
        return low, high

    @staticmethod
    def _module_side(module):
        if not isinstance(module, dict):
            return "NONE"
        side = SetupReasoningEngine._direction(
            module.get("direction") or module.get("bias") or module.get("directional_bias")
        )
        if side != "NONE":
            return side
        best = module.get("best")
        return SetupReasoningEngine._direction(best.get("direction")) if isinstance(best, dict) else "NONE"

    def _candidate_directions(self, mtf, sweep):
        directions = []
        primary = self._direction((mtf or {}).get("entry"))
        if primary != "NONE":
            directions.append((primary, "H4_STRUCTURE"))
        # A counter-trend scenario is admitted only after an actual one-sided
        # sweep and a causally confirmed post-sweep structure break.
        if isinstance(sweep, dict) and sweep.get("is_sweep") and not sweep.get("ambiguous_sweep"):
            post = sweep.get("post_structure") or {}
            if post.get("confirmed"):
                reversal = self._direction(post.get("direction"))
                if reversal != "NONE" and reversal not in [side for side, _ in directions]:
                    sweep_side = str(sweep.get("sweep_side", "")).upper()
                    expected = "LONG" if sweep_side == "SELL_SIDE" or sweep.get("sell_side") else (
                        "SHORT" if sweep_side == "BUY_SIDE" or sweep.get("buy_side") else "NONE"
                    )
                    if reversal == expected:
                        directions.append((reversal, "CONFIRMED_SWEEP_REVERSAL"))
        return directions

    def _targets(self, direction, entry, liquidity, external_structure,
                 fvg=None, orderblocks=None, structure=None):
        levels = []
        expected_liquidity = "BUY_SIDE" if direction == "LONG" else "SELL_SIDE"
        for item in liquidity or []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != expected_liquidity:
                continue
            price = self._number(item.get("price"))
            if price is not None and ((direction == "LONG" and price > entry) or (direction == "SHORT" and price < entry)):
                levels.append(price)

        expected_fvg = "BEARISH" if direction == "LONG" else "BULLISH"
        for item in fvg or []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != expected_fvg or item.get("filled"):
                continue
            key = "from" if direction == "LONG" else "to"
            price = self._number(item.get(key))
            if price is not None and ((direction == "LONG" and price > entry) or (direction == "SHORT" and price < entry)):
                levels.append(price)

        expected_ob = "BEARISH" if direction == "LONG" else "BULLISH"
        for item in orderblocks or []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != expected_ob or item.get("mitigated"):
                continue
            key = "low" if direction == "LONG" else "high"
            price = self._number(item.get(key))
            if price is not None and ((direction == "LONG" and price > entry) or (direction == "SHORT" and price < entry)):
                levels.append(price)

        for collection in (structure, external_structure):
            for item in collection or []:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "")).upper()
                price = self._number(item.get("price"))
                if price is None:
                    continue
                if direction == "LONG" and label in {"HH", "LH"} and price > entry:
                    levels.append(price)
                elif direction == "SHORT" and label in {"LL", "HL"} and price < entry:
                    levels.append(price)
        return sorted(set(levels), reverse=(direction == "SHORT"))

    def _evidence(self, direction, mtf, sweep, structure, ote, htf_orderblock,
                  htf_fvg, smt, unicorn, cisd, volume_profile, institutional,
                  orderbook, correlation, market_phase, market_regime):
        supporting, opposing = [], []
        expected = "BULLISH" if direction == "LONG" else "BEARISH"
        for label, module in (
            ("weekly", {"direction": (mtf or {}).get("weekly")}),
            ("daily", {"direction": (mtf or {}).get("daily")}),
            ("4H", {"direction": (mtf or {}).get("h4")}),
            ("SMT", smt), ("Unicorn", unicorn), ("CISD", cisd),
            ("Volume Profile", volume_profile), ("Institutional Flow", institutional),
            ("HTF Order Block", htf_orderblock), ("HTF FVG", htf_fvg),
            ("Market Regime", market_regime),
        ):
            side = self._module_side(module)
            if side == "NONE":
                continue
            (supporting if side == direction else opposing).append(
                f"{label} {side}"
            )
        post = (sweep or {}).get("post_structure") or {}
        if (sweep or {}).get("is_sweep"):
            sweep_side = str((sweep or {}).get("sweep_side", "")).upper()
            sweep_direction = "LONG" if sweep_side == "SELL_SIDE" or (sweep or {}).get("sell_side") else (
                "SHORT" if sweep_side == "BUY_SIDE" or (sweep or {}).get("buy_side") else "NONE"
            )
            if sweep_direction == direction and post.get("confirmed"):
                supporting.append("Liquidity sweep + confirmed post-sweep structure")
            elif sweep_direction != "NONE":
                opposing.append("Opposing liquidity sweep")
        if isinstance(structure, list):
            events = [x for x in structure if isinstance(x, dict) and (x.get("choch") or x.get("bos"))]
            if events:
                event_side = self._direction(events[-1].get("direction"))
                if event_side != "NONE":
                    (supporting if event_side == direction else opposing).append(
                        f"15m {events[-1].get('label', 'structure break')} {event_side}"
                    )
        reference_side = self._direction((mtf or {}).get("entry"))
        if isinstance(orderbook, dict) and (orderbook.get("active") or orderbook.get("trade_flow_active")):
            book_supportive = bool(orderbook.get("supportive"))
            book_opposing = bool(orderbook.get("opposing"))
            if reference_side != direction:
                book_supportive, book_opposing = book_opposing, book_supportive
            if book_supportive:
                supporting.append("Order flow supports entry")
            if book_opposing:
                opposing.append("Order flow counterpressure")
        if isinstance(correlation, dict) and correlation.get("active"):
            corr_supportive = bool(correlation.get("supportive"))
            corr_opposing = bool(correlation.get("counterpressure"))
            if reference_side != direction:
                corr_supportive, corr_opposing = corr_opposing, corr_supportive
            if corr_supportive:
                supporting.append("Cross-market correlation supports entry")
            if corr_opposing:
                opposing.append("Cross-market counterpressure")
        phase = (market_phase or {}).get("phase") if isinstance(market_phase, dict) else None
        if phase:
            supporting.append(f"Market phase: {phase}")
        return supporting, opposing

    def generate(self, *, base_entry, mtf, structure, fvg, orderblocks,
                 current_price, candles=None, liquidity_sweep=None, ote=None,
                 market_regime=None, htf_orderblock=None, htf_fvg=None, smt=None,
                 unicorn=None, cisd=None, volume_profile=None, institutional=None,
                 orderbook=None, correlation=None, market_phase=None,
                 liquidity=None, external_structure=None,
                 higher_timeframe_orderblocks=None, higher_timeframe_fvg=None):
        base_entry = base_entry if isinstance(base_entry, dict) else {}
        current = self._number(current_price)
        if current is None or current <= 0:
            return {"candidates": [], "selected": base_entry, "reason": "current_price_unavailable"}
        mtf = mtf if isinstance(mtf, dict) else {}
        fvg = fvg if isinstance(fvg, list) else []
        orderblocks = orderblocks if isinstance(orderblocks, list) else []
        sweep = liquidity_sweep if isinstance(liquidity_sweep, dict) else {}
        regime = market_regime if isinstance(market_regime, dict) else {}
        ote_bounds = None
        if isinstance(ote, dict):
            a, b = self._number(ote.get("fib62")), self._number(ote.get("fib79"))
            if a and b and a != b:
                ote_bounds = min(a, b), max(a, b)
        require_ote = str(regime.get("regime", "")).upper() in {"TRENDING_UP", "TRENDING_DOWN"}
        atr_buffer = 0.0
        atr_value = None
        if candles:
            try:
                from utils.atr import atr as calculate_atr
                atr_value = self._number(calculate_atr(candles, period=14))
                if atr_value and atr_value > 0:
                    atr_buffer = atr_value * 0.10
            except (TypeError, ValueError, OverflowError, ZeroDivisionError):
                pass

        candidates = []
        for direction, direction_source in self._candidate_directions(mtf, sweep):
            expected = "BULLISH" if direction == "LONG" else "BEARISH"
            poi_items = []
            poi_groups = (
                ("ORDER_BLOCK", orderblocks), ("FVG", fvg),
                ("HTF_ORDER_BLOCK", higher_timeframe_orderblocks or []),
                ("HTF_FVG", higher_timeframe_fvg or []),
            )
            for source, items in poi_groups:
                for index, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("type", "")).upper() != expected:
                        continue
                    if item.get("mitigated") if source in {"ORDER_BLOCK", "HTF_ORDER_BLOCK"} else item.get("filled"):
                        continue
                    bounds = self._bounds(item, "FVG" if source in {"FVG", "HTF_FVG"} else "OB")
                    if not bounds:
                        continue
                    low, high = bounds
                    ote_overlap = bool(ote_bounds and ote_bounds[0] <= high and ote_bounds[1] >= low)
                    if require_ote and direction == self._direction(mtf.get("entry")) and ote_bounds and not ote_overlap:
                        continue
                    poi_items.append((source, index, item, low, high, ote_overlap))
            for source, index, item, low, high, ote_overlap in poi_items:
                inside = low <= current <= high
                post = sweep.get("post_structure") or {}
                sweep_expected = (direction == "LONG" and bool(sweep.get("sell_side"))) or (
                    direction == "SHORT" and bool(sweep.get("buy_side"))
                )
                market_confirmed = bool(
                    sweep.get("is_sweep") and sweep_expected and post.get("confirmed")
                    and self._direction(post.get("direction")) == direction
                )
                if direction == "LONG":
                    entry_price = current if inside and market_confirmed else high
                    stop = low - atr_buffer
                    executable = inside and market_confirmed or current > entry_price
                else:
                    entry_price = current if inside and market_confirmed else low
                    stop = high + atr_buffer
                    executable = inside and market_confirmed or current < entry_price
                if not executable or entry_price <= 0 or stop <= 0:
                    continue
                risk = abs(entry_price - stop)
                if risk <= 0 or (direction == "LONG" and stop >= entry_price) or (
                    direction == "SHORT" and stop <= entry_price
                ):
                    continue
                target_fvg = list(fvg) + list(higher_timeframe_fvg or [])\n                target_obs = list(orderblocks) + list(higher_timeframe_orderblocks or [])\n                targets = self._targets(\n                    direction, entry_price, liquidity, external_structure,\n                    fvg=target_fvg, orderblocks=target_obs, structure=structure,\n                )
                projected_rr = abs(targets[-1] - entry_price) / risk if targets else None
                support, opposition = self._evidence(
                    direction, mtf, sweep, structure, ote, htf_orderblock, htf_fvg,
                    smt, unicorn, cisd, volume_profile, institutional, orderbook,
                    correlation, market_phase, regime,
                )
                # Counterpressure changes the requested fill location, not the
                # existence of a structurally valid setup. Move deeper into
                # the same POI instead of discarding it.
                pressure_present = bool(opposition)
                entry_depth_reason = None
                if pressure_present and not (inside and market_confirmed):
                    deeper = low + (high - low) * 0.38 if direction == "LONG" else high - (high - low) * 0.38
                    if (direction == "LONG" and current > deeper) or (direction == "SHORT" and current < deeper):
                        entry_price = deeper
                        risk = abs(entry_price - stop)
                        projected_rr = abs(targets[-1] - entry_price) / risk if targets and risk > 0 else None
                        entry_depth_reason = "Counterpressure moved the limit deeper inside the same POI"
                structure_events = [
                    event for event in (structure or [])
                    if isinstance(event, dict) and (event.get("choch") or event.get("bos"))
                ]
                latest_structure = structure_events[-1] if structure_events else {}
                structure_aligned = self._direction(latest_structure.get("direction")) == direction
                orderflow_supportive = bool(
                    isinstance(orderbook, dict) and (
                        orderbook.get("supportive") if self._direction(mtf.get("entry")) == direction
                        else orderbook.get("opposing")
                    )
                )
                candidate_distance = abs(entry_price - current)
                atr_distance = candidate_distance / atr_value if atr_value and atr_value > 0 else None
                distance_pct = candidate_distance / current if current > 0 else None
                distance_label = (
                    "YAKIN GİRİŞ"
                    if distance_pct is not None and distance_pct <= 0.02
                    and (atr_distance is None or atr_distance <= 2.0)
                    else "UZAK GİRİŞ"
                )
                candidate = {
                    "valid": True, "direction": direction, "entry": entry_price,
                    "stop_loss": stop, "stop_source": source.lower(),
                    "entry_type": "MARKET" if inside and market_confirmed else "LIMIT",
                    "entry_type_reason": "Confirmed sweep reclaim inside POI" if inside and market_confirmed else "Pullback to selected POI",
                    "requires_pullback": not (inside and market_confirmed),
                    "poi_source": source, "poi_zone": {"low": low, "high": high},
                    "ote_confluence": ote_overlap, "stop_buffer": atr_buffer,
                    "entry_reason_code": "ENTRY_READY", "entry_zone_crossed": False,
                    "entry_too_far": False, "score": max(50, int(base_entry.get("score", 50) or 50)),
                    "reason": "Structurally valid POI candidate",
                    "checks": list(base_entry.get("checks") or []),
                    "setup_candidate_id": f"{direction}:{source}:{index}",
                    "direction_source": direction_source,
                    "projected_target": targets[-1] if targets else None,
                    "projected_rr": projected_rr,
                    "supporting_evidence": support,
                    "opposing_evidence": opposition,
                    "reasoning": (
                        f"{direction} {source}: POI {low:g}-{high:g}; "
                        + ("sweep reclaim confirmed" if inside and market_confirmed else "price can retrace to POI")
                        + (f"; {entry_depth_reason}" if entry_depth_reason else "")
                    ),
                }
                candidates.append(candidate)

        if not candidates:
            return {"candidates": [], "selected": base_entry, "reason": "no_additional_executable_poi"}

        # Lexicographic scenario selection; no additive votes or confidence score.
        # Prefer a valid structural target, then best projected RR, confirmed
        # reversal trigger, OTE overlap, POI overlap, then nearer executable entry.
        def rank(candidate):
            rr = candidate.get("projected_rr")
            distance = abs(candidate["entry"] - current) / current
            return (
                candidate.get("projected_target") is not None,
                rr if rr is not None else -1.0,
                candidate.get("structure_aligned", False),
                candidate.get("direction_source") == "CONFIRMED_SWEEP_REVERSAL",
                candidate.get("ote_confluence", False),
                candidate.get("orderflow_supportive", False),
                distance * -1.0,
                candidate.get("poi_source") in {"ORDER_BLOCK", "HTF_ORDER_BLOCK"},
            )
        selected = max(candidates, key=rank)
        selected = dict(selected)
        selected["reasoning"] = selected["reasoning"] + (
            f"; {len(candidates)} candidates compared; selected by target geometry, "
            "projected R, confirmed structure and POI location"
        )
        return {"candidates": candidates, "selected": selected, "reason": "best_structural_candidate"}
