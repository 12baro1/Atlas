import math

"""Single integrated SMC candidate adapter; specialist motors remain evidence-only."""

def _mandatory_confluence_reason(analysis, direction, entry):
    """Require aligned H4 CHoCH plus a live OB/FVG intersection inside that leg's OTE."""
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    structure = analysis.get("smc_h4_structure")
    structure = structure if isinstance(structure, list) else []
    choch_events = [item for item in structure if isinstance(item, dict) and item.get("choch") is True]
    if not choch_events:
        return "SMC_REQUIRED_CHoCH_MISSING"
    latest_choch = choch_events[-1]
    if str(latest_choch.get("direction") or "").upper() != expected:
        return "SMC_REQUIRED_CHoCH_DIRECTION_MISMATCH"

    ote = analysis.get("smc_ote")
    if not isinstance(ote, dict):
        return "SMC_REQUIRED_OTE_MISSING"
    try:
        ote_low, ote_high = sorted((float(ote.get("fib62")), float(ote.get("fib79"))))
        entry = float(entry)
    except (TypeError, ValueError, OverflowError):
        return "SMC_REQUIRED_OTE_INVALID"
    if not (math.isfinite(ote_low) and math.isfinite(ote_high) and 0 < ote_low < ote_high):
        return "SMC_REQUIRED_OTE_INVALID"

    orderblocks = analysis.get("smc_orderblocks")
    orderblocks = orderblocks if isinstance(orderblocks, list) else []
    fvgs = analysis.get("smc_fvg")
    fvgs = fvgs if isinstance(fvgs, list) else []
    active_obs = []
    for item in orderblocks:
        if not isinstance(item, dict) or str(item.get("type") or "").upper() != expected or item.get("mitigated"):
            continue
        try:
            low, high = sorted((float(item.get("low")), float(item.get("high"))))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(low) and math.isfinite(high) and 0 < low < high:
            active_obs.append((low, high))
    if not active_obs:
        return "SMC_REQUIRED_VALID_OB_MISSING"

    active_fvgs = []
    for item in fvgs:
        if not isinstance(item, dict) or str(item.get("type") or "").upper() != expected or item.get("filled"):
            continue
        try:
            low, high = sorted((float(item.get("from")), float(item.get("to"))))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(low) and math.isfinite(high) and 0 < low < high:
            active_fvgs.append((low, high))
    if not active_fvgs:
        return "SMC_REQUIRED_VALID_FVG_MISSING"

    for ob_low, ob_high in active_obs:
        for fvg_low, fvg_high in active_fvgs:
            common_low = max(ote_low, ob_low, fvg_low)
            common_high = min(ote_high, ob_high, fvg_high)
            if common_low < common_high and common_low <= entry <= common_high:
                return None
    return "SMC_OB_FVG_OTE_CONFLUENCE_OR_ENTRY_MISSING"


def generate(result, data=None):
    from strategy_lab import math, STRATEGY_NAMES, _value, _configured_partial_tp_weights, trend_structure, displacement, dealing_range, liquidity_draw, poi_freshness, breaker_validation, reclaim_acceptance, inducement_proxy, smc_narrative
    """Build the single SMC setup from the integrated SMC specialist world.

    This adapter reads the pre-selector SMC entry/risk geometry. It deliberately
    does not inspect the legacy signal or decision verdict: those are downstream
    gates and must not suppress an otherwise valid SMC setup before the shared
    seven-strategy filter gets to evaluate it.
    """
    if not isinstance(result, dict):
        return None
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    entry_state = analysis.get("entry") if isinstance(analysis.get("entry"), dict) else result.get("entry")
    entry_state = entry_state if isinstance(entry_state, dict) else {}
    source_risk = result.get("risk") if isinstance(result.get("risk"), dict) else {}
    dynamic_tp = result.get("dynamic_tp") if isinstance(result.get("dynamic_tp"), dict) else {}
    signal = result.get("signal") if isinstance(result.get("signal"), dict) else {}
    direction = str(entry_state.get("direction") or signal.get("signal") or "").upper()
    try:
        entry_value = entry_state.get("entry")
        if entry_value is None:
            entry_value = source_risk.get("entry")
        stop_value = source_risk.get("stop_loss")
        if stop_value is None:
            stop_value = entry_state.get("stop_loss")
        entry = float(entry_value)
        stop = float(stop_value)
        target_values = [
            float(source_risk.get(key) if source_risk.get(key) is not None else dynamic_tp.get(key))
            for key in ("tp1", "tp2", "tp3")
        ]
    except (TypeError, ValueError, OverflowError):
        return None
    if direction not in {"LONG", "SHORT"} or not all(
        math.isfinite(value) and value > 0 for value in (entry, stop, *target_values)
    ):
        return None
    mandatory_reason = _mandatory_confluence_reason(analysis, direction, entry)
    if mandatory_reason:
        analysis["smc_mandatory_gate_reason"] = mandatory_reason
        return None
    analysis.pop("smc_mandatory_gate_reason", None)
    if direction == "LONG" and not (stop < entry < target_values[0] <= target_values[1] <= target_values[2]):
        return None
    if direction == "SHORT" and not (target_values[0] >= target_values[1] >= target_values[2] and target_values[0] < entry < stop):
        return None
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return None
    reasoning = entry_state.get("setup_reasoning") if isinstance(entry_state.get("setup_reasoning"), dict) else {}
    reasons = list(reasoning.get("supporting_evidence") or [])
    if reasoning.get("thesis"):
        reasons.insert(0, str(reasoning["thesis"]))
    if not reasons:
        reasons = ["Integrated SMC specialist evidence"]
    # SMC submotors enrich specialist evidence but never veto or select trades.
    data = data if isinstance(data, dict) else {}
    smc_candles = data.get("15m") or []
    htf_candles = data.get("4h") or data.get("1h") or []
    price = _value(smc_candles[-1], "close") if smc_candles else entry
    structure_info = trend_structure(htf_candles)
    range_info = dealing_range(htf_candles, price)
    draw_info = liquidity_draw(htf_candles, direction)
    analysis_zones = []
    for key in ("orderblocks", "order_blocks", "fvg", "fvg_zones", "poi", "zones"):
        value = analysis.get(key)
        if isinstance(value, list):
            analysis_zones.extend(value)
    fresh_poi = poi_freshness(analysis_zones, price, smc_candles)
    breaker_info = breaker_validation(analysis.get("orderblocks") or analysis.get("order_blocks") or [], smc_candles)
    reclaim_info = reclaim_acceptance(smc_candles, entry, direction)
    inducement_info = inducement_proxy(htf_candles, direction)
    displacement_info = displacement(smc_candles, source_risk.get("atr") or 0)
    narrative_info = smc_narrative(direction, structure_info, range_info, draw_info, displacement_info, fresh_poi)
    plan = {
        "status": "RAW_SETUP",
        "strategy_id": "smc",
        "strategy": STRATEGY_NAMES["smc"],
        "direction": direction,
        "entry_type": str(entry_state.get("entry_type") or "MARKET").upper(),
        "entry": entry,
        "stop_loss": stop,
        "tp1": target_values[0],
        "tp2": target_values[1],
        "tp3": target_values[2],
        "rr_tp1": round(abs(target_values[0] - entry) / risk_distance, 3),
        "rr_tp2": round(abs(target_values[1] - entry) / risk_distance, 3),
        "rr_tp3": round(abs(target_values[2] - entry) / risk_distance, 3),
        "strength": float(signal.get("confidence") or (analysis.get("setup_quality") or {}).get("score") or 0),
        "target_model": "SMC_STRUCTURAL",
        "experimental": False,
        "reasons": reasons,
        "supporting_event_ids": list(reasoning.get("supporting_event_ids") or []),
        "opposing_event_ids": list(reasoning.get("opposing_event_ids") or []),
        "opposing_evidence": list(reasoning.get("opposing_evidence") or []),
        "market_context": list(reasoning.get("market_context") or []),
        "partial_exit_weights": (
            source_risk.get("target_rebased_weights")
            or source_risk.get("partial_exit_weights")
            or _configured_partial_tp_weights()
        ),
        "atr": source_risk.get("atr"),
        "smc_evidence": {
            "market_structure": structure_info,
            "dealing_range": range_info,
            "liquidity_draw": draw_info,
            "poi_freshness": fresh_poi,
            "breaker_validation": breaker_info,
            "reclaim_acceptance": reclaim_info,
            "inducement_proxy": inducement_info,
            "displacement": displacement_info,
            "narrative": narrative_info,
        },
    }
    plan["reasons"].append(f"SMC narrative evidence {narrative_info['evidence_count']}/5; diagnostic only")
    return plan
