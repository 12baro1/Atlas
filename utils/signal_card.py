"""
signal_card.py
Atlas için tek yönlü, net ve okunabilir işlem önerisi (sinyal kartı) üretir.
Manuel işlem kullanıcısına: YÖN, giriş/stop/TP, kalite puanı ve çelişkileri tek bakışta sunar.
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


def _verdict(decision, signal, entry):
    """Tek bir net karar döndürür: AL, SAT, BEKLE veya ATLA."""
    action = str((decision or {}).get("action", "WAIT") or "").upper()
    signal_dir = str((signal or {}).get("signal", "WAIT") or "").upper()
    entry_type = str((entry or {}).get("entry_type") or "").upper()
    entry_reason = str((entry or {}).get("entry_type_reason") or "").lower()

    if action in ("EXECUTE", "EXECUTE_WITH_CAUTION") and signal_dir in ("LONG", "SHORT"):
        return ("AL" if signal_dir == "LONG" else "SAT", signal_dir, None)
    if action == "WAIT":
        wait_reason = (signal or {}).get("wait_reason") or (decision or {}).get("reason")
        return ("BEKLE", None, wait_reason)

    # A pending LIMIT pullback is not an executable trade or a broken setup.
    if entry_type == "LIMIT" and "wait for pullback" in entry_reason:
        return ("BEKLE", None, (entry or {}).get("entry_type_reason") or "Geri çekilme bekleniyor")

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

    verdict_label, direction, verdict_reason = _verdict(decision, signal, entry)
    pending_pullback = (
        verdict_label == "BEKLE"
        and str(entry.get("entry_type") or "").upper() == "LIMIT"
        and "wait for pullback" in str(entry.get("entry_type_reason") or "").lower()
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
        "entry_type_reason": entry.get("entry_type_reason") or "",
        "synthetic_tp_targets": bool(dynamic_tp.get("synthetic_targets", False)),
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
    action = str(card.get("decision_action") or "").upper()
    entry_type = str(card.get("entry_type") or "").upper()
    pending_limit = entry_type == "LIMIT" and "wait for pullback" in str(card.get("entry_type_reason") or "").lower()
    executable = action in ("EXECUTE", "EXECUTE_WITH_CAUTION") and card.get("direction") in ("LONG", "SHORT")
    if pending_limit and not executable:
        headline = "KARAR: ŞİMDİ GİRME | EMİR: LIMIT (FİYAT GELİNCE)"
    elif executable:
        headline = "KARAR: İŞLEME GİR | EMİR: " + (entry_type if entry_type in ("MARKET", "LIMIT") else "GİRİŞİ TEYİT ET")
    else:
        headline = "KARAR: İŞLEME GİRME"
    lines = [line, "  " + str(card["symbol"]) + "  |  " + headline, line]
    if card["direction"]:
        lines.append(f"  Yön        : {card['direction']}")
    lines.append(f"  Girdi      : {card['entry']}")
    if executable:
        shown_entry_type = entry_type if entry_type in ("MARKET", "LIMIT") else "GİRİŞİ TEYİT ET"
    elif pending_limit:
        shown_entry_type = "LIMIT (fiyat bölgesine gelirse)"
    else:
        shown_entry_type = "YOK (işlem açma)"
    lines.append(f"  Emir türü  : {shown_entry_type}")
    if card.get("entry_type_reason"):
        entry_reason = str(card["entry_type_reason"])
        if "wait for pullback" in entry_reason.lower():
            entry_reason = "Fiyatın LIMIT giriş bölgesine dönmesi gerekiyor"
        lines.append(f"  Giriş nedeni: {entry_reason}")
    lines.append(f"  Stop       : {card['stop_loss']}")
    if card["tp_levels"]:
        tp_label = "TP1/2/3 (sentetik RR)" if card.get("synthetic_tp_targets") else "TP1/2/3"
        lines.append(f"  {tp_label:<12}: {' / '.join(str(t) for t in card['tp_levels'])}")
    lines.append(f"  RR         : {card['rr']}")
    lines.append(f"  Kalite     : {card['setup_quality']}/100  (Confluence {card['confluence']})")
    confidence = card.get("confidence")
    try:
        confidence_text = f"{float(confidence):g}"
    except (TypeError, ValueError):
        confidence_text = "-"
    if executable:
        phase_summary = f"{card['market_phase']} | Yön {card['direction']} (skor {confidence_text}/100)"
    elif pending_limit:
        phase_summary = f"{card['market_phase']} | LIMIT fiyat bölgesi bekleniyor"
    else:
        phase_summary = f"{card['market_phase']} | Uygun işlem yok"
    lines.append(f"  Piyasa Fz  : {phase_summary}")
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
