"""Central aggregation of Atlas motor evidence.

This layer ranks the evidence for an already structural, executable POI.
It never creates a trade and never turns secondary motor disagreement into
a hard veto. EntryEngine/RiskEngine/TradeQualityEngine remain responsible
for structural and execution safety.
"""
import math


class SetupAggregator:
    """Normalize motor outputs into one auditable LONG/SHORT setup consensus."""

    @staticmethod
    def _number(value, default=0.0):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _side(value):
        raw = str(value or "").strip().upper()
        if raw in {"LONG", "BULLISH", "BUY", "BUY_SIDE"}:
            return "LONG"
        if raw in {"SHORT", "BEARISH", "SELL", "SELL_SIDE"}:
            return "SHORT"
        return "NONE"

    def aggregate(
        self, *, entry=None, mtf=None, confirmation=None, liquidity_sweep=None,
        ote=None, htf_orderblock=None, htf_fvg=None, smt=None, unicorn=None,
        cisd=None, volume_profile=None, institutional=None, orderbook=None,
        correlation=None, market_phase=None, market_regime=None, breaker=None,
        trendline_sweep=None, optimization=None, confluence=None,
        setup_quality=None, trade_quality=None,
    ):
        entry = entry if isinstance(entry, dict) else {}
        direction = self._side(entry.get("direction"))
        evidence = []

        def add(name, side, weight, confidence=60.0, source="motor"):
            side = self._side(side)
            weight = max(0.0, self._number(weight))
            confidence = min(100.0, max(0.0, self._number(confidence, 60.0)))
            if side == "NONE" or weight <= 0:
                return
            evidence.append({
                "motor": name,
                "side": side,
                "weight": round(weight, 4),
                "confidence": round(confidence, 2),
                "source": source,
                "aligned": side == direction if direction != "NONE" else None,
            })

        # The selected MTF structure is the directional anchor, not a veto.
        mtf = mtf if isinstance(mtf, dict) else {}
        add("mtf_structure", mtf.get("entry"), 3.0, 75.0, "primary_structure")

        # Entry confirmation is recorded as evidence. It is not counted as an
        # independent vote when it merely repeats the same MTF direction.
        confirmation = confirmation if isinstance(confirmation, dict) else {}
        if confirmation.get("confirmed"):
            add("entry_confirmation", entry.get("direction"), 1.5, 70.0, "confirmation")
        elif confirmation.get("direction") or confirmation.get("bias"):
            add("entry_confirmation", confirmation.get("direction") or confirmation.get("bias"), 0.8, 45.0, "soft_confirmation")

        sweep = liquidity_sweep if isinstance(liquidity_sweep, dict) else {}
        if sweep.get("is_sweep"):
            if sweep.get("sell_side"):
                add("liquidity_sweep", "LONG", 1.6, sweep.get("strength_score", 60), "liquidity")
            if sweep.get("buy_side"):
                add("liquidity_sweep", "SHORT", 1.6, sweep.get("strength_score", 60), "liquidity")

        def add_module(name, module, weight, fallback=None):
            if not isinstance(module, dict) or not module.get("active", module.get("valid", False)):
                return
            raw = module.get("direction") or module.get("bias") or fallback
            confidence = module.get("confidence", module.get("strength_score", 60))
            add(name, raw, weight, confidence)

        add_module("smt", smt, 1.0)
        add_module("unicorn", unicorn, 1.1, (unicorn or {}).get("best", {}).get("direction") if isinstance(unicorn, dict) and isinstance(unicorn.get("best"), dict) else None)
        add_module("cisd", cisd, 1.1)
        add_module("volume_profile", volume_profile, 0.8)
        add_module("institutional_flow", institutional, 0.9)

        # Order-book and correlation payloads often express support/pressure
        # relative to the requested side instead of returning a raw direction.
        if isinstance(orderbook, dict) and (orderbook.get("active") or orderbook.get("trade_flow_active")) and direction != "NONE":
            if orderbook.get("supportive"):
                add("orderbook", direction, 0.7, orderbook.get("confidence", 65.0), "microstructure")
            if orderbook.get("opposing"):
                add("orderbook_counterpressure", "SHORT" if direction == "LONG" else "LONG", 0.7, orderbook.get("confidence", 65.0), "microstructure")
        elif isinstance(orderbook, dict):
            add_module("orderbook", orderbook, 0.7)

        if isinstance(correlation, dict) and correlation.get("active") and direction != "NONE":
            if correlation.get("supportive"):
                add("correlation", direction, 0.5, correlation.get("confidence", 60.0), "cross_market")
            if correlation.get("counterpressure"):
                add("correlation_counterpressure", "SHORT" if direction == "LONG" else "LONG", 0.5 + self._number(correlation.get("counterpressure_score"), 0.0), 60.0, "cross_market")
        elif isinstance(correlation, dict):
            add_module("correlation", correlation, 0.5)

        regime_bias = market_regime.get("directional_bias") if isinstance(market_regime, dict) else None
        if isinstance(market_regime, dict) and (market_regime.get("active") or regime_bias):
            add("market_regime", regime_bias, 0.7, market_regime.get("confidence", 60.0))

        # POI context is supporting evidence only when a valid directional POI
        # exists. It cannot create a setup in the absence of EntryEngine output.
        if entry.get("valid") and direction != "NONE":
            for name, module, weight in (
                ("ote", ote, 1.0),
                ("htf_orderblock", htf_orderblock, 1.0),
                ("htf_fvg", htf_fvg, 0.8),
            ):
                if isinstance(module, dict) and module.get("valid"):
                    add(name, module.get("direction") or module.get("type") or direction, weight, module.get("confidence", 70.0), "poi_context")

        if isinstance(breaker, list):
            expected = "BULLISH" if direction == "LONG" else "BEARISH"
            if direction != "NONE":
                matching = any(isinstance(x, dict) and x.get("breaker") and str(x.get("type", "")).upper() == expected for x in breaker)
                opposing = any(isinstance(x, dict) and x.get("breaker") and str(x.get("type", "")).upper() != expected for x in breaker)
                if matching:
                    add("breaker", direction, 0.7, 65.0)
                if opposing:
                    add("breaker_counterpressure", "SHORT" if direction == "LONG" else "LONG", 0.5, 55.0)

        if isinstance(trendline_sweep, dict) and trendline_sweep.get("active"):
            sweep_side = self._side(trendline_sweep.get("direction"))
            if sweep_side == "NONE":
                raw = str(trendline_sweep.get("direction", "")).upper()
                sweep_side = "LONG" if raw == "SELL_SIDE" else "SHORT" if raw == "BUY_SIDE" else "NONE"
            add("trendline_sweep", sweep_side, 0.7, 65.0)

        # EntryOptimizer has already converted price/level evidence into a
        # shared entry. Preserve its evidence verbatim in the central ledger.
        optimization = optimization if isinstance(optimization, dict) else {}
        existing_motors = {item["motor"] for item in evidence}
        for item in optimization.get("evidence", []) or []:
            if not isinstance(item, dict):
                continue
            source_name = str(item.get("source", "entry_optimizer"))
            # The optimizer consumes several of the same motor outputs. Do
            # not count the same motor twice in the central consensus.
            if source_name in existing_motors:
                continue
            bias = str(item.get("bias", "")).upper()
            side = direction if bias in {"ALIGNED", "SUPPORTIVE", "CONFIRMED"} else (
                "SHORT" if direction == "LONG" else "LONG" if direction == "SHORT" else "NONE"
            ) if bias in {"OPPOSED", "COUNTERPRESSURE", "MANIPULATION_RISK", "WEAK"} else "NONE"
            add(
                item.get("source", "entry_optimizer"),
                side,
                item.get("weight", 0.5),
                item.get("confidence", 60.0),
                "entry_optimizer",
            )

        support = {side: 0.0 for side in ("LONG", "SHORT")}
        oppose = {side: 0.0 for side in ("LONG", "SHORT")}
        total_weight = 0.0
        for item in evidence:
            weight = item["weight"] * (0.5 + item["confidence"] / 200.0)
            support[item["side"]] += weight
            total_weight += weight

        scores = {}
        for side in ("LONG", "SHORT"):
            other = "SHORT" if side == "LONG" else "LONG"
            denominator = support[side] + support[other]
            scores[side] = round(50.0 + 50.0 * (support[side] - support[other]) / denominator, 2) if denominator else 50.0

        evidence_leader = max(scores, key=scores.get)
        selected_score = scores.get(direction, 50.0) if direction != "NONE" else max(scores.values())
        selected_evidence = [item for item in evidence if item["side"] == direction] if direction != "NONE" else []
        counter_evidence = [item for item in evidence if item["side"] != direction] if direction != "NONE" else []
        structural_valid = bool(entry.get("valid")) and direction in {"LONG", "SHORT"}
        allowed = bool(trade_quality.get("allowed", True)) if isinstance(trade_quality, dict) else True

        return {
            "version": 1,
            "direction": direction if structural_valid else "NONE",
            "structural_valid": structural_valid,
            "trade_quality_allowed": allowed,
            "score": round(selected_score, 2),
            "scores": scores,
            "support_weight": round(support.get(direction, 0.0), 4) if direction != "NONE" else 0.0,
            "counter_weight": round(support.get("SHORT" if direction == "LONG" else "LONG", 0.0), 4) if direction != "NONE" else 0.0,
            "support_count": len(selected_evidence),
            "counter_count": len(counter_evidence),
            "evidence": evidence,
            "counterpressure": counter_evidence,
            "entry_price": entry.get("entry") if structural_valid else None,
            "entry_type": entry.get("entry_type") if structural_valid else None,
            "optimizer_applied": bool(optimization.get("applied")),
            "evidence_leader": evidence_leader,
            "evidence_leader_matches_structure": evidence_leader == direction if direction != "NONE" else False,
            "market_phase": (market_phase or {}).get("phase") if isinstance(market_phase, dict) else market_phase,
            "confluence_score": self._number((confluence or {}).get("score"), 0.0) if isinstance(confluence, dict) else 0.0,
            "setup_quality_score": self._number((setup_quality or {}).get("score"), 0.0) if isinstance(setup_quality, dict) else 0.0,
            "trade_quality_reason": (trade_quality or {}).get("reason") if isinstance(trade_quality, dict) else None,
            "selection_rule": "best evidence score among structurally valid POI setups; secondary conflicts are soft evidence",
        }
