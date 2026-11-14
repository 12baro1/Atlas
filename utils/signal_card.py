"""
signal_card.py
Atlas için tek yönlü, net ve okunabilir işlem önerisi (sinyal kartı) üretir.
Manuel işlem kullanıcısına: yön, giriş/stop/TP ve setup gerekçesini tek bakışta sunar.
"""

import math


def _num(value, digits=2):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _price(value):
    """Keep small-market price precision visible in terminal output.

    Two-decimal rounding made valid prices such as 0.173846 look like 0.17,
    hiding the actual stop distance and sometimes making SL equal to entry.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 12)


def _verdict(decision, signal, entry, risk=None):
    """Tek bir net karar döndürür: AL, SAT, BEKLE veya ATLA."""
    action = str((decision or {}).get("action", "WAIT") or "").upper()
    signal_dir = str((signal or {}).get("signal", "WAIT") or "").upper()
    entry_type = str((entry or {}).get("entry_type") or "").upper()
    entry_dir = str((entry or {}).get("direction") or "").upper()
    if entry_dir not in ("LONG", "SHORT"):
        entry_dir = None

    # LIMIT orders are conditional and must never be shown as immediate entry permission.
    risk = risk if isinstance(risk, dict) else {}
    entry_is_valid = (
        (entry or {}).get("valid") is not False
        and (entry or {}).get("entry") is not None
        and ((entry or {}).get("stop_loss") is not None or risk.get("stop_loss") is not None)
    )
    risk_has_target = any(risk.get(key) is not None for key in ("tp1", "tp2", "tp3"))
    risk_is_valid = bool(risk) and risk_has_target and risk.get("risk_setup_valid", True) is not False
    pending_limit = (
        entry_type == "LIMIT"
        and entry_is_valid
        and risk_is_valid
        and action in ("EXECUTE", "EXECUTE_WITH_CAUTION")
    )
    if entry_type == "LIMIT":
        if pending_limit:
            pending_direction = signal_dir if signal_dir in ("LONG", "SHORT") else entry_dir
            return ("BEKLE", pending_direction, (entry or {}).get("entry_type_reason") or "Fiyatın LIMIT giriş bölgesine dönmesi gerekiyor")
        return ("ATLA", entry_dir, (decision or {}).get("reason") or risk.get("risk_setup_reason") or "LIMIT setup geçerli değil")
    if (
        entry_type == "MARKET"
        and action in ("EXECUTE", "EXECUTE_WITH_CAUTION")
        and signal_dir in ("LONG", "SHORT")
        and entry_is_valid
        and risk_is_valid
    ):
        return ("AL" if signal_dir == "LONG" else "SAT", signal_dir, None)

    # WAIT is not an actionable terminal decision; show it as no-entry.
    if action == "WAIT":
        wait_reason = (signal or {}).get("wait_reason") or (decision or {}).get("reason")
        # Keep the analyzed MTF direction visible even when the final decision is WAIT.
        return ("ATLA", entry_dir, wait_reason)

    return ("ATLA", None, (decision or {}).get("reason"))


def _label_items(payload, key):
    """Modül bazlı ayar/blok listesini (label delta) sözlük dizisine çevirir."""
    out = []
    for item in (payload or {}).get(key, []) if isinstance((payload or {}).get(key, []), list) else []:
        if isinstance(item, dict):
            label = item.get("label") or item.get("name") or item.get("module")
            delta = item.get("delta")
            out.append({"label": label, "delta": delta})
        elif isinstance(item, str):
            out.append({"label": item, "delta": None})
    return out


def build_signal_card(result):
    """result_payload (engine.analyze() çıktısı) -> okunabilir sinyal kartı sözlüğü."""
    signal = result.get("signal") or {}
    decision = result.get("decision") or {}
    risk = result.get("risk") or {}
    rr = result.get("rr") or {}
    dynamic_tp = result.get("dynamic_tp") or {}
    analysis = result.get("analysis") or {}
    setup_quality = analysis.get("setup_quality") or {}
    confluence = analysis.get("confluence") or {}
    market_phase = analysis.get("market_phase") or {}
    entry = analysis.get("entry") or {}
    setup_reasoning = entry.get("setup_reasoning") or {}
    symbol = result.get("symbol", "UNKNOWN")

    verdict_label, direction, verdict_reason = _verdict(decision, signal, entry, risk)
    entry_is_valid = (
        entry.get("valid") is not False
        and entry.get("entry") is not None
        and (entry.get("stop_loss") is not None or risk.get("stop_loss") is not None)
    )
    risk_has_target = any(risk.get(key) is not None for key in ("tp1", "tp2", "tp3"))
    risk_is_valid = bool(risk) and risk_has_target and risk.get("risk_setup_valid", True) is not False
    pending_pullback = (
        str(entry.get("entry_type") or "").upper() == "LIMIT"
        and entry_is_valid
        and risk_is_valid
        and str(decision.get("action") or "").upper() in ("EXECUTE", "EXECUTE_WITH_CAUTION")
    )

    card = {
        "symbol": symbol,
        "verdict": verdict_label,
        "direction": direction,
        "decision_action": decision.get("action", "WAIT"),
        "signal": signal.get("signal", "WAIT"),
        "confidence": _num(signal.get("confidence", 0)),
        "grade": signal.get("grade", ""),
        "strength": signal.get("strength", ""),
        "market_phase": market_phase.get("phase", "Bilinmiyor"),
        "setup_quality": _num(setup_quality.get("score", 0)),
        "confluence": _num(confluence.get("score", 0)),
        "setup_allowed": bool(setup_quality.get("trade_allowed", False)),
        "entry": None,
        "entry_type": str(entry.get("entry_type") or "BELİRSİZ").upper(),
        "entry_valid": (entry.get("valid") is not False and entry.get("entry") is not None and (entry.get("stop_loss") is not None or risk.get("stop_loss") is not None)),
        "risk_setup_valid": bool(risk) and any(risk.get(key) is not None for key in ("tp1", "tp2", "tp3")) and risk.get("risk_setup_valid", True) is not False,
        "entry_type_reason": entry.get("entry_type_reason") or "",
        "entry_distance_label": entry.get("entry_distance_label") or "",
        "entry_distance_pct": _num(entry.get("entry_distance_pct"), 3),
        "entry_distance_atr": _num(entry.get("entry_distance_atr"), 2),
        "requires_pullback": str(entry.get("entry_type") or "").upper() == "LIMIT",
        "setup_thesis": setup_reasoning.get("thesis") or "",
        "supporting_evidence": list(setup_reasoning.get("supporting_evidence") or []),
        "opposing_evidence": list(setup_reasoning.get("opposing_evidence") or []),
        "market_context": list(setup_reasoning.get("market_context") or []),
        "candidate_count": int(setup_reasoning.get("candidate_count", 0) or 0),
        "synthetic_tp_targets": bool(dynamic_tp.get("synthetic_targets", False)),
        "stop_loss": None,
        "tp_levels": [],
        "rr": None,
        "net_rr": None,
        "target_max_rr": None,
        "weighted_rr": None,
        "weighted_net_rr": None,
        "partial_exit_weights": {},
        "selected_tp": None,
        "position_size": None,
        "capital_at_risk": None,
        "critical_blocks": [],
        "soft_adjustments": [],
        "bonuses": [],
        "reason": verdict_reason,
        "summary": "",
    }

    entry_price = entry.get("entry")
    if entry_price is not None:
        card["entry"] = _price(entry_price)
    stop = risk.get("stop_loss") or entry.get("stop_loss")
    if stop is not None:
        card["stop_loss"] = _price(stop)

    for tp in (risk.get("tp1") or dynamic_tp.get("tp1"),
               risk.get("tp2") or dynamic_tp.get("tp2"),
               risk.get("tp3") or dynamic_tp.get("tp3")):
        if tp is not None:
            card["tp_levels"].append(_price(tp))

    card["target_max_rr"] = _num(
        risk.get("target_max_rr")
        or rr.get("target_max_rr")
        or risk.get("rr")
    )
    card["weighted_rr"] = _num(
        risk.get("weighted_rr")
        if risk.get("weighted_rr") is not None
        else rr.get("weighted_rr")
    )
    card["weighted_net_rr"] = _num(
        risk.get("weighted_net_rr")
        if risk.get("weighted_net_rr") is not None
        else rr.get("weighted_net_rr")
    )
    card["partial_exit_weights"] = (
        risk.get("partial_exit_weights")
        or rr.get("partial_exit_weights")
        or {}
    )
    card["rr"] = (
        card["weighted_rr"]
        if card["weighted_rr"] is not None
        else _num(risk.get("rr") or rr.get("rr"))
    )
    card["net_rr"] = (
        card["weighted_net_rr"]
        if card["weighted_net_rr"] is not None
        else _num(risk.get("net_rr"))
    )
    card["selected_tp"] = risk.get("selected_tp") or rr.get("selected_tp")
    card["position_size"] = _num(risk.get("position_size"))
    card["capital_at_risk"] = _num(risk.get("capital_at_risk"))

    card["critical_blocks"] = list(decision.get("critical_blockers") or [])
    for source in (
        decision.get("quality_blockers"),
        (decision.get("trade_quality") or {}).get("blockers") if isinstance(decision.get("trade_quality"), dict) else None,
    ):
        if isinstance(source, list):
            for item in source:
                if item and item not in card["critical_blocks"]:
                    card["critical_blocks"].append(item)
    if str(decision.get("action") or "").upper() == "WAIT":
        wait_reasons = (
            signal.get("wait_reason"),
            entry.get("entry_type_reason"),
            decision.get("reason"),
        )
        for item in wait_reasons:
            if item and item not in card["critical_blocks"]:
                card["critical_blocks"].append(str(item))
    if pending_pullback:
        # These are downstream consequences of a pending entry, not separate faults.
        pending_entry_blocks = {
            "Signal direction invalid",
            "Entry invalid",
            "Risk cannot be calculated",
            "RR below quality minimum: None < 3",
        }
        card["critical_blocks"] = [
            item for item in card["critical_blocks"]
            if item not in pending_entry_blocks
            and not str(item).startswith("RR below quality minimum:")
        ]
    card["soft_adjustments"] = _label_items(decision, "soft_blockers")
    card["bonuses"] = _label_items(decision, "bonuses")
    if verdict_label in ("ATLA", "BEKLE") and verdict_reason and verdict_reason not in card["critical_blocks"]:
        card["critical_blocks"].append(verdict_reason)

    card["summary"] = _summarize(card)
    return card



def build_selected_strategy_card(result):
    """Build the one canonical terminal card from SevenStrategyLab.selected.

    Every strategy reaches this adapter only after the shared common filter and
    single-decision selector. The adapter still validates
    finite prices, direction, order type, target ordering and positive risk.
    """
    result = result if isinstance(result, dict) else {}
    report = result.get("strategy_lab") or {}
    selected = report.get("selected")
    if not isinstance(selected, dict):
        card = build_signal_card(result)
        card.update({
            "verdict": "ATLA",
            "direction": None,
            "decision_action": "SKIP",
            "entry": None,
            "stop_loss": None,
            "tp_levels": [],
            "rr": None,
            "net_rr": None,
            "reason": "Yedi strateji içinde seçilebilir, doğrulanmış bir işlem planı yok.",
            "critical_blocks": ["NO_SELECTED_STRATEGY_PLAN"],
        })
        card["summary"] = _summarize(card)
        return card

    strategy_id = str(selected.get("strategy_id") or "").strip()
    direction = str(selected.get("direction") or "").upper()
    entry_type = str(selected.get("entry_type") or "").upper()
    try:
        entry = float(selected.get("entry"))
        stop = float(selected.get("stop_loss"))
        targets = [float(selected.get(key)) for key in ("tp1", "tp2", "tp3")]
    except (TypeError, ValueError, OverflowError):
        entry = stop = None
        targets = []
    valid_numbers = (
        entry is not None and stop is not None and len(targets) == 3
        and all(math.isfinite(value) and value > 0 for value in [entry, stop, *targets])
    )
    geometry_valid = False
    if valid_numbers and direction == "LONG":
        geometry_valid = stop < entry < targets[0] < targets[1] < targets[2]
    elif valid_numbers and direction == "SHORT":
        geometry_valid = stop > entry > targets[0] > targets[1] > targets[2]
    risk_distance = abs(entry - stop) if valid_numbers else 0.0
    risk_validation = selected.get("risk_validation") or {}
    risk_plan = selected.get("risk_plan") or {}
    executable = (
        risk_validation.get("eligible") is True
        and isinstance(risk_plan, dict)
        and risk_plan.get("final_geometry_reconciled") is True
        and risk_plan.get("risk_setup_valid") is True
        and geometry_valid and risk_distance > 0
        and entry_type in {"MARKET", "LIMIT"}
        and selected.get("status") in {"SELECTED", "CANDIDATE"}
    )
    if not executable:
        card = build_signal_card(result)
        card.update({
            "verdict": "ATLA", "direction": None, "decision_action": "SKIP",
            "entry": None, "stop_loss": None, "tp_levels": [],
            "rr": None, "net_rr": None,
            "reason": "Seçilen strateji planı ortak fiyat/geometri doğrulamasından geçemedi.",
            "critical_blocks": ["SELECTED_PLAN_GEOMETRY_INVALID"],
        })
        card["summary"] = _summarize(card)
        return card

    rr_values = [round(abs(target - entry) / risk_distance, 4) for target in targets]
    estimated_net_rr = selected.get("estimated_net_rr")
    if estimated_net_rr is None:
        estimated_net_rr = selected.get("estimated_net_rr_tp1")
    try:
        estimated_net_rr = float(estimated_net_rr) if estimated_net_rr is not None else None
    except (TypeError, ValueError, OverflowError):
        estimated_net_rr = None
    if estimated_net_rr is not None and not math.isfinite(estimated_net_rr):
        estimated_net_rr = None
    reasons = list(selected.get("reasons") or [])
    card = {
        "symbol": result.get("symbol") or report.get("symbol") or "UNKNOWN",
        "verdict": "AL" if direction == "LONG" and entry_type == "MARKET" else
                   "SAT" if direction == "SHORT" and entry_type == "MARKET" else "BEKLE",
        "direction": direction,
        "decision_action": "EXECUTE",
        "signal": direction,
        "confidence": _num(selected.get("strength")),
        "grade": "",
        "strength": "STRATEGY_CANDIDATE",
        "market_phase": (report.get("regime") or {}).get("label", "UNKNOWN"),
        "setup_quality": _num(selected.get("strength")),
        "confluence": None,
        "setup_allowed": True,
        "entry": _price(entry),
        "entry_type": entry_type,
        "entry_valid": True,
        "risk_setup_valid": True,
        "entry_type_reason": "Koşullu LIMIT planı" if entry_type == "LIMIT" else "",
        "entry_distance_label": "",
        "entry_distance_pct": None,
        "entry_distance_atr": None,
        "requires_pullback": entry_type == "LIMIT",
        "setup_thesis": selected.get("strategy") or strategy_id,
        "supporting_evidence": reasons,
        "opposing_evidence": [],
        "market_context": [],
        "candidate_count": report.get("candidate_count", 0),
        "synthetic_tp_targets": selected.get("target_model") == "R_MULTIPLE_FALLBACK",
        "stop_loss": _price(stop),
        "tp_levels": [_price(value) for value in targets],
        "rr": _num(risk_plan.get("weighted_rr")) or rr_values[0],
        "net_rr": _num(risk_plan.get("weighted_net_rr")) if risk_plan.get("weighted_net_rr") is not None else estimated_net_rr,
        "target_max_rr": _num(risk_plan.get("target_max_rr")) or rr_values[-1],
        "weighted_rr": _num(risk_plan.get("weighted_rr")) or rr_values[0],
        "weighted_net_rr": _num(risk_plan.get("weighted_net_rr")) if risk_plan.get("weighted_net_rr") is not None else estimated_net_rr,
        "partial_exit_weights": risk_plan.get("partial_exit_weights") or {},
        "selected_tp": risk_plan.get("selected_tp") or "weighted_partial_exit",
        "position_size": _num(risk_plan.get("position_size")),
        "capital_at_risk": _num(risk_plan.get("capital_at_risk")),
        "critical_blocks": [],
        "soft_adjustments": [],
        "bonuses": [],
        "reason": None,
        "summary": "",
        "strategy_id": strategy_id,
        "strategy": selected.get("strategy") or strategy_id,
        "experimental": bool(selected.get("experimental")),
        "target_model": selected.get("target_model"),
        "estimated_net_rr_tp1": estimated_net_rr,
    }
    card["summary"] = _summarize(card)
    return card

def _summarize(card):
    """Tek satırlık dürüst özet."""
    if card["verdict"] in ("BEKLE", "ATLA"):
        return f"{card['symbol']}: {card['verdict']} - {card['reason']}. Şu an işlem açma."
    entry = card["entry"]
    sl = card["stop_loss"]
    tps = "/".join(str(t) for t in card["tp_levels"]) or "yok"
    return (
        f"{card['verdict']} {card['symbol']} @ {entry} | SL {sl} | TP {tps} | "
        f"Ağırlıklı RR ~{card['rr']} | Net RR ~{card.get('net_rr')} | "
        f"{len(card['critical_blocks'])} kritik blok, {len(card['soft_adjustments'])} yumuşak düzeltme"
    )


def format_card_text(card):
    """Terminalde yalnızca işlem kararına yarayan bilgileri göster."""
    line = "=" * 42
    action = str(card.get("decision_action") or "").upper()
    entry_type = str(card.get("entry_type") or "").upper()
    pending_limit = (
        entry_type == "LIMIT"
        and card.get("entry_valid")
        and card.get("risk_setup_valid")
        and action in ("EXECUTE", "EXECUTE_WITH_CAUTION")
        and card.get("direction") in ("LONG", "SHORT")
        and card.get("entry") is not None
        and card.get("stop_loss") is not None
    )
    executable = (
        entry_type == "MARKET"
        and action in ("EXECUTE", "EXECUTE_WITH_CAUTION")
        and card.get("entry_valid")
        and card.get("risk_setup_valid")
        and card.get("direction") in ("LONG", "SHORT")
    )
    no_trade = not pending_limit and not executable

    if pending_limit:
        headline = "LIMIT BEKLE"
    elif executable:
        headline = "İŞLEME GİR"
    else:
        headline = "İŞLEME GİRME"

    lines = [line, f"  {card['symbol']}  |  {headline}", line]
    if card.get("direction") in ("LONG", "SHORT"):
        lines.append(f"  Yön       : {card['direction']}")

    if no_trade:
        reason = card.get("reason") or "Giriş şartları oluşmadı."
        lines.append(f"  Neden     : {reason}")
        blockers = [str(item) for item in card.get("critical_blocks") or [] if item and str(item) != str(reason)]
        if blockers:
            lines.append("  Engeller  : " + " | ".join(blockers[:4]))
        # No-trade output intentionally hides hypothetical prices and targets.
        # Only actionable MARKET/LIMIT setups may display executable levels.
        lines.append("  Not       : Geçerli MARKET/LIMIT girişi bulunmadı; emir açma.")
        lines.append(line)
        return "\n".join(lines)

    if pending_limit:
        lines.append("  Emir      : LIMIT (fiyat giriş seviyesine gelirse)")
        condition = str(card.get("entry_type_reason") or "Fiyat LIMIT giriş seviyesine gelmeden işlem açma")
        if "wait for pullback" in condition.lower():
            condition = "Fiyatın LIMIT giriş bölgesine dönmesi gerekiyor"
        lines.append("  Koşul     : " + condition)
    elif entry_type in ("MARKET", "LIMIT"):
        lines.append(f"  Emir      : {entry_type}")
    else:
        lines.append("  Emir      : BELİRSİZ (teyit gerekli)")

    if card.get("entry") is not None:
        lines.append(f"  Giriş     : {card['entry']}")
    if pending_limit and card.get("entry_distance_pct") is not None:
        distance = f"%{card['entry_distance_pct']}"
        if card.get("entry_distance_label"):
            distance = f"{card['entry_distance_label']} ({distance})"
        lines.append(f"  Mesafe    : {distance}")
    if card.get("stop_loss") is not None:
        lines.append(f"  Stop Loss : {card['stop_loss']}")
    if card.get("tp_levels"):
        label = "TP (sentetik RR)" if card.get("synthetic_tp_targets") else "TP"
        for index, target in enumerate(card["tp_levels"][:3], start=1):
            lines.append(f"  {label}{index} : {target}")
    if card.get("rr") is not None:
        lines.append(f"  Ağırlıklı RR : {card['rr']}")
    if card.get("net_rr") is not None:
        lines.append(f"  Net RR       : {card['net_rr']}")
    if card.get("target_max_rr") is not None:
        lines.append(f"  TP max RR    : {card['target_max_rr']}")
    if card.get("setup_thesis"):
        lines.append(f"  Setup     : {card['setup_thesis']}")
    if card.get("supporting_evidence"):
        lines.append("  Destek    : " + " | ".join(card["supporting_evidence"][:5]))
    if card.get("opposing_evidence"):
        lines.append("  Karşı kanıt: " + " | ".join(card["opposing_evidence"][:5]))
    if card.get("market_context"):
        lines.append("  Bağlam    : " + " | ".join(card["market_context"][:5]))
    lines.append(line)
    return "\n".join(lines)
