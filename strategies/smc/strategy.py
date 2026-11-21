"""Single integrated SMC candidate adapter; specialist motors remain evidence-only."""
import math

from shared.analysis_services import _value
from shared.market_structure_services import trend_structure, displacement
from strategies.candidate import _configured_partial_tp_weights, STRATEGY_NAMES
from strategies.smc.submotors import (
    dealing_range,
    liquidity_draw,
    poi_freshness,
    breaker_validation,
    reclaim_acceptance,
    inducement_proxy,
    narrative as smc_narrative,
)


def _mandatory_confluence_reason(analysis, direction, entry):
    """Require aligned H4 CHoCH and at least one active directional OB or FVG.

    OTE is optional and may guide entry placement, but never blocks a setup.
    """
    expected = "BULLISH" if direction == "LONG" else "BEARISH"
    structure = analysis.get("smc_h4_structure")
    structure = structure if isinstance(structure, list) else []
    choch_events = [
        item for item in structure
        if isinstance(item, dict) and item.get("choch") is True
    ]
    if not choch_events:
        return "SMC_REQUIRED_CHoCH_MISSING"
    if str(choch_events[-1].get("direction") or "").upper() != expected:
        return "SMC_REQUIRED_CHoCH_DIRECTION_MISMATCH"

    # An intervening opposite structural break invalidates the older CHoCH.
    # Preserve compatibility when structure evidence has no ordered break events.
    last_choch_index = next(
        i for i in range(len(structure) - 1, -1, -1)
        if isinstance(structure[i], dict) and structure[i].get("choch") is True
    )
    # If the producer supplies 4H candle indices, avoid trading a CHoCH
    # whose age is no longer relevant. Unknown ages are not guessed.
    latest_choch = structure[last_choch_index]
    age_bars = latest_choch.get("age_bars")
    if age_bars is not None:
        try:
            age = float(age_bars)
            if not math.isfinite(age) or age < 0 or age > 30:
                return "SMC_CHoCH_STALE"
        except (TypeError, ValueError, OverflowError):
            return "SMC_CHoCH_STALE"
    opposite = "BEARISH" if expected == "BULLISH" else "BULLISH"
    for event in structure[last_choch_index + 1:]:
        if not isinstance(event, dict):
            continue
        if (event.get("bos") is True or event.get("choch") is True) and (
            str(event.get("direction") or "").upper() == opposite
        ):
            return "SMC_CHoCH_INVALIDATED_BY_OPPOSITE_BREAK"

    try:
        entry = float(entry)
    except (TypeError, ValueError, OverflowError):
        return "SMC_INVALID_ENTRY"
    if not math.isfinite(entry) or entry <= 0:
        return "SMC_INVALID_ENTRY"

    zones = []
    orderblocks = analysis.get("smc_orderblocks")
    for item in orderblocks if isinstance(orderblocks, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").upper() != expected or item.get("mitigated"):
            continue
        try:
            low, high = sorted((float(item.get("low")), float(item.get("high"))))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(low) and math.isfinite(high) and 0 < low < high:
            zones.append(("OB", low, high))

    fvgs = analysis.get("smc_fvg")
    for item in fvgs if isinstance(fvgs, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").upper() != expected or item.get("filled"):
            continue
        try:
            low, high = sorted((float(item.get("from")), float(item.get("to"))))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(low) and math.isfinite(high) and 0 < low < high:
            zones.append(("FVG", low, high))

    if not zones:
        return "SMC_REQUIRED_VALID_OB_OR_FVG_MISSING"
    if not any(low <= entry <= high for _, low, high in zones):
        # A LIMIT entry can be placed at the nearest active OB/FVG boundary.
        # A MARKET entry outside the zone is not an SMC POI entry.
        return "SMC_ENTRY_OUTSIDE_VALID_OB_FVG"

    # OTE is advisory only: malformed or absent OTE must not veto the setup.
    ote = analysis.get("smc_ote")
    if isinstance(ote, dict):
        try:
            ote_low, ote_high = sorted((float(ote.get("fib62")), float(ote.get("fib79"))))
            if not (math.isfinite(ote_low) and math.isfinite(ote_high) and 0 < ote_low < ote_high):
                analysis["smc_ote_advisory_invalid"] = True
            else:
                analysis.pop("smc_ote_advisory_invalid", None)
        except (TypeError, ValueError, OverflowError):
            analysis["smc_ote_advisory_invalid"] = True
    return None

def generate(result, data=None):
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
        target_values = []
        for key in ("tp1", "tp2", "tp3"):
            value = source_risk.get(key)
            if value is None:
                value = dynamic_tp.get(key)
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                value = None
            target_values.append(value)
        # Missing upstream TP geometry may be recovered only from confirmed
        # opposing swing levels in the independent shared geometry service.
        # Never synthesize arbitrary R-multiple or ATR targets.
        if any(value is None or not math.isfinite(value) or value <= 0 for value in target_values):
            from strategy_lab import _finalize_candidate_geometry
            from shared.analysis_services import _atr
            data_sets = [
                (data or {}).get(tf) or [] for tf in ("15m", "1h", "4h", "1d", "1w")
                if (data or {}).get(tf)
            ] if isinstance(data, dict) else []
            atr = source_risk.get("atr")
            if atr is None and isinstance(data, dict):
                atr = _atr(data.get("15m") or [])
            fallback = {"direction": direction, "entry": entry,
                        "stop_loss": stop, "atr": atr}
            reason = _finalize_candidate_geometry(fallback, data_sets)
            if reason:
                analysis["smc_mandatory_gate_reason"] = f"SMC_STRUCTURAL_TARGET_RECOVERY:{reason}"
                return None
            stop = fallback["stop_loss"]
            target_values = [fallback[key] for key in ("tp1", "tp2", "tp3")]
    except (TypeError, ValueError, OverflowError):
        analysis["smc_mandatory_gate_reason"] = "SMC_MISSING_ENTRY_STOP_OR_THREE_TARGETS"
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
        analysis["smc_mandatory_gate_reason"] = "SMC_INVALID_LONG_ENTRY_STOP_TARGET_ORDER"
        return None
    if direction == "SHORT" and not (target_values[0] >= target_values[1] >= target_values[2] and target_values[0] < entry < stop):
        analysis["smc_mandatory_gate_reason"] = "SMC_INVALID_SHORT_ENTRY_STOP_TARGET_ORDER"
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
