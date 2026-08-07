"""
signal_card.py
Atlas için tek yönlü, net ve okunabilir işlem önerisi (sinyal kartı) üretir.
Manuel işlem kullanıcısına: YÖN, giriş/stop/TP, kalite puanı ve çelişkileri tek bakışta sunar.
"""


def _num(value, digits=2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _verdict(decision, signal):
    """Tek bir net karar döndürür: AL, SAT, BEKLE veya ATLA."""
    action = str((decision or {}).get("action", "WAIT") or "").upper()
    signal_dir = str((signal or {}).get("signal", "WAIT") or "").upper()

    if action in ("EXECUTE", "EXECUTE_WITH_CAUTION") and signal_dir in ("LONG", "SHORT"):
        return ("AL" if signal_dir == "LONG" else "SAT", signal_dir, None)
    if action == "WAIT":
        wait_reason = (signal or {}).get("wait_reason") or (decision or {}).get("reason")
        return ("BEKLE", None, wait_reason)
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
    symbol = result.get("symbol", "UNKNOWN")

    verdict_label, direction, verdict_reason = _verdict(decision, signal)

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
        "stop_loss": None,
        "tp_levels": [],
        "rr": None,
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
        card["entry"] = _num(entry_price)
    stop = risk.get("stop_loss") or entry.get("stop_loss")
    if stop is not None:
        card["stop_loss"] = _num(stop)

    for tp in (risk.get("tp1") or dynamic_tp.get("tp1"),
               risk.get("tp2") or dynamic_tp.get("tp2"),
               risk.get("tp3") or dynamic_tp.get("tp3")):
        if tp is not None:
            card["tp_levels"].append(_num(tp))

    card["rr"] = _num(risk.get("rr") or rr.get("rr"))
    card["selected_tp"] = risk.get("selected_tp") or rr.get("selected_tp")
    card["position_size"] = _num(risk.get("position_size"))
    card["capital_at_risk"] = _num(risk.get("capital_at_risk"))

    card["critical_blocks"] = list(decision.get("critical_blockers") or [])
    card["soft_adjustments"] = _label_items(decision, "soft_blockers")
    card["bonuses"] = _label_items(decision, "bonuses")
    if verdict_label in ("ATLA", "BEKLE") and verdict_reason:
        card["critical_blocks"].append(verdict_reason)

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
        f"RR ~{card['rr']} | Kalite {card['setup_quality']}/100 | "
        f"{len(card['critical_blocks'])} kritik blok, {len(card['soft_adjustments'])} yumuşak düzeltme"
    )


def format_card_text(card):
    """Kartı terminalde yazdırılabilir, tek bakışta okunan metne çevirir."""
    line = "=" * 46
    lines = [line, f"  {card['symbol']}  ->  {card['verdict']}", line]
    if card["direction"]:
        lines.append(f"  Yön        : {card['direction']}")
    lines.append(f"  Girdi      : {card['entry']}")
    lines.append(f"  Stop       : {card['stop_loss']}")
    if card["tp_levels"]:
        lines.append(f"  TP1/2/3    : {' / '.join(str(t) for t in card['tp_levels'])}")
    lines.append(f"  RR         : {card['rr']}")
    lines.append(f"  Kalite     : {card['setup_quality']}/100  (Confluence {card['confluence']})")
    lines.append(f"  Piyasa Fz  : {card['market_phase']}  |  Sinyal {card['signal']} ({card['confidence']}%)")
    if card["selected_tp"]:
        lines.append(f"  Hedef TP   : {card['selected_tp']}")
    if card["position_size"]:
        lines.append(f"  Pozisyon   : {card['position_size']} birim | Risk {card['capital_at_risk']} USD")
    if card["critical_blocks"]:
        lines.append("  ENGELLER   : " + "; ".join(card["critical_blocks"]))
    if card["soft_adjustments"]:
        parts = []
        for item in card["soft_adjustments"]:
            if item["delta"] is not None:
                parts.append(f"{item['label']} ({item['delta']:+d})")
            else:
                parts.append(item["label"])
        lines.append("  Düzeltme   : " + ", ".join(parts))
    if card["bonuses"]:
        parts = []
        for item in card["bonuses"]:
            if item["delta"] is not None:
                parts.append(f"{item['label']} ({item['delta']:+d})")
            else:
                parts.append(item["label"])
        lines.append("  Bonus      : " + ", ".join(parts))
    lines.append(line)
    return "\n".join(lines)
