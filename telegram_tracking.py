"""Chat-scoped theoretical signals. All transitions share the pool transaction."""
import json
import time

from core.candle import Candle
from tracking_history import BAR, MINUTE, EvidenceMissing, indexed, matches
from telegram_prices import tracked_levels
from trade_journal import TradeJournal


SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_follows(
 chat TEXT NOT NULL, symbol TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(chat,symbol));
CREATE TABLE IF NOT EXISTS chat_plans(
 chat TEXT NOT NULL, symbol TEXT NOT NULL, revision INTEGER NOT NULL,
 setup_id TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(chat,symbol,revision));
CREATE INDEX IF NOT EXISTS chat_plan_state ON chat_plans(symbol,state);
CREATE TABLE IF NOT EXISTS chat_events(
 id INTEGER PRIMARY KEY, chat TEXT NOT NULL, symbol TEXT NOT NULL,
 revision INTEGER NOT NULL, event TEXT NOT NULL, message TEXT NOT NULL, delivered INTEGER DEFAULT 0,
 UNIQUE(chat,symbol,revision,event));
CREATE TABLE IF NOT EXISTS chat_event_delivery(
 event_id INTEGER PRIMARY KEY REFERENCES chat_events(id),
 state TEXT NOT NULL CHECK(state IN ('sending','retry','uncertain','failed','sent')),
 attempts INTEGER NOT NULL, next_at INTEGER NOT NULL, message_id INTEGER);
CREATE INDEX IF NOT EXISTS chat_event_pending ON chat_events(chat,delivered,id);
"""


class CandleSimulation(TradeJournal):
    """Reuse journal execution rules with persistence owned by the pool transaction."""
    def __init__(self):
        pass

    def _persist_signal_outcome(self, outcome):
        pass

    def _signal_outcome_expiry_hours(self):
        return 0


def event(conn, chat, symbol, revision, kind, message, plan):
    message += "\n" + tracked_levels(plan)
    conn.execute("INSERT OR IGNORE INTO chat_events(chat,symbol,revision,event,message) VALUES(?,?,?,?,?)",
                 (chat, symbol, revision, kind, f"{symbol.replace(':USDT', '')} — {message}"))


def transition(conn, chat, symbol, revision, setup, *, announce):
    current = conn.execute("SELECT setup_id,state,payload FROM chat_plans WHERE chat=? AND symbol=? AND revision=?",
                           (chat, symbol, revision)).fetchone()
    if current:
        previous_id, state, raw = current
        old = json.loads(raw)
        if setup and previous_id == setup["setup_id"] and state != "INVALIDATED":
            return
        if state in {"ACTIVE","AMBIGUOUS"}:
            return
        if state == "WAITING":
            old["resolved_at"] = int(time.time()*1000)
            conn.execute("UPDATE chat_plans SET state='INVALIDATED',payload=? WHERE chat=? AND symbol=? AND revision=?",
                         (json.dumps(old),chat, symbol, revision))
            if announce and not setup:
                event(conn, chat, symbol, revision, "INVALIDATED", "SETUP KALDIRILDI\nNeden: Strateji yapısı bozuldu. Yeni setup bekleniyor.", old)
    if not setup:
        return
    revision += 1
    costs = dict(setup.get("execution_costs") or {}, entry_type=setup["entry_type"])
    outcome = dict(symbol=symbol, direction=setup["direction"], entry=setup["entry_price"],
                   stop_loss=setup["stop_loss"], tp1=setup["tp1"], tp2=setup["tp2"], tp3=setup["tp3"],
                   strategy=setup["strategy_name"], strategy_id=setup["strategy_id"], opened_at=int(time.time()*1000), status="PENDING",
                   partial_weights=costs.get("partial_exit_weights") or CandleSimulation()._signal_partial_weights(), realized_r=0.0,
                   entry_reached=False, payload={"execution_costs":costs})
    conn.execute("UPDATE chat_follows SET revision=? WHERE chat=? AND symbol=?", (revision, chat, symbol))
    conn.execute("INSERT INTO chat_plans VALUES(?,?,?,?,?,?)",
                 (chat, symbol, revision, setup["setup_id"], "WAITING", json.dumps(outcome)))
    if announce:
        label = "YENİ SETUP" if not current or state in {"INVALIDATED","CLOSED"} else "SETUP GÜNCELLENDİ"
        previous = f"\nEski: {old['direction']} | {old['strategy']}" if current else ""
        event(conn, chat, symbol, revision, "SETUP", f"{label}{previous}\nYeni: {outcome['direction']} | {outcome['strategy']}", outcome)


def next_bar(plan):
    # The journal starts on the first 15m open strictly after publication.
    return plan.get("next_bar_time", (plan.get("last_processed_candle_time", plan["opened_at"]) // BAR + 1) * BAR)


def apply_bar(plan, candle, width):
    """Return False without mutating the plan if OHLC cannot order its events."""
    if getattr(candle, "volume", None) == 0:
        plan["last_processed_candle_time"] = candle.time
        return True
    long = plan["direction"] == "LONG"
    stop = plan.get("trailing_stop", plan["stop_loss"])
    hits = plan.get("tps_hit", [])
    targets = [plan[f"tp{i}"] for i in (1, 2, 3) if i not in hits]
    touched = [p for p in targets if (candle.high >= p if long else candle.low <= p)]
    stopped = candle.low <= stop if long else candle.high >= stop
    market = not plan["entry_reached"] and plan["payload"]["execution_costs"]["entry_type"] == "MARKET"
    entry = candle.open if market else plan["entry"]
    if not plan["entry_reached"]:
        if market:
            if not (stop < entry < targets[0] if long else stop > entry > targets[0]):
                return False
        elif not candle.low <= entry <= candle.high:
            plan["last_processed_candle_time"] = candle.time
            return True
        elif touched or stopped:
            return False

    if len(touched) > 1 and width > 1:
        return False
    if touched:
        moved_stops = [entry if target == plan["tp1"] else plan["tp1"]
                       for target in touched if target != plan["tp3"]]
        if stopped or any(candle.low <= p if long else candle.high >= p for p in moved_stops):
            return False
    if market:
        plan.update(entry=entry, entry_reached=True, entry_reached_at=candle.time)
    CandleSimulation().resolve_signal_outcome(plan, [candle])
    if plan["status"] != "PENDING":
        plan["resolved_at"] = candle.time + width
    return True


def resolve_bar(plan, symbol, candle, width, history, now):
    verified = plan.get("verified_until", 0)
    if candle.time + width <= verified:
        return False
    if candle.time >= verified and apply_bar(plan, candle, width):
        plan["verified_until"] = candle.time + width
        return False
    if history is None:
        raise EvidenceMissing("Mum içinde giriş, hedef veya stop sırası belirsiz")
    if width == MINUTE:
        children = history.ticks(symbol, candle.time)
        if not matches(candle, children):
            raise EvidenceMissing("İşlem geçmişi 1m mumun fiyat ve hacmini doğrulamıyor")
        previous_price = children[0].open
        for tick in children:
            crossed_entry = min(previous_price, tick.close) < plan["entry"] < max(previous_price, tick.close)
            previous_price = tick.close
            if tick.time < verified:
                continue
            if not plan["entry_reached"] and crossed_entry:
                raise EvidenceMissing("İşlem fiyatları giriş seviyesini atladı")
            if not apply_bar(plan, tick, 1):
                raise EvidenceMissing("İşlem fiyatı plan seviyeleriyle uyuşmuyor")
            plan["verified_until"] = tick.time + 1
            if plan["status"] != "PENDING":
                break
        return True
    for step in ((5 * MINUTE, MINUTE) if width == BAR else (MINUTE,)):
        children = child_range(history, symbol, candle.time, width, step, now)
        if all(children) and matches(candle, children):
            break
    else:
        raise EvidenceMissing("Alt mum geçmişi eksik veya üst mumla uyuşmuyor")
    for child in children:
        resolve_bar(plan, symbol, child, step, history, now)
        if plan["status"] != "PENDING":
            break
    return True


def child_range(history, symbol, start, span, width, now):
    bars = indexed(history.candles(symbol, start, width, span // width), width, now)
    return [bars.get(t) for t in range(start, start + span, width)]


def recover_missing_bar(history, symbol, start, now):
    for width in (5 * MINUTE, MINUTE):
        children = child_range(history, symbol, start, BAR, width, now)
        if all(children):
            return Candle(start, children[0].open, max(c.high for c in children),
                          min(c.low for c in children), children[-1].close, sum(c.volume for c in children))
    raise EvidenceMissing("15m geçmişi eksik, alt mumlar aralığı tamamlamıyor")


def evaluate(symbol, state, raw, now, candles=None, history=None):
    plan = json.loads(raw)
    if plan.get("manual_review") or plan.get("retry_at", 0) > now:
        return
    start = next_bar(plan)
    count = min(96, (now - start) // BAR)
    if count <= 0:
        return
    # Older code set entry_reached before proving the order and omitted its timestamp.
    if state == "AMBIGUOUS" and plan["entry_reached"] and not plan.get("entry_reached_at"):
        plan["entry_reached"] = False
    try:
        if history:
            candles = history.candles(symbol, start, BAR, count)
        bars = indexed(candles or [], BAR, now)
        last_available = max(bars, default=0)
        if not history and last_available < start:
            return
        for stamp in range(start, start + count * BAR, BAR):
            candle = bars.get(stamp)
            recovered = False
            if candle is None:
                if history is None or stamp in bars:
                    raise EvidenceMissing("15m geçmişinde eksik veya çelişkili mum")
                candle = recover_missing_bar(history, symbol, stamp, now)
                recovered = True
            # Pin the parent while verified children advance the journal cursor.
            plan["next_bar_time"] = stamp
            prices = [candle.open, candle.high, candle.low, candle.close]
            if plan.get("parent_prices", prices) != prices:
                raise EvidenceMissing("Kısmen doğrulanmış 15m mumun fiyatları değişti")
            plan["parent_prices"] = prices
            refined = resolve_bar(plan, symbol, candle, BAR, history, now)
            plan["next_bar_time"] = stamp + BAR
            plan.pop("parent_prices")
            plan.pop("verified_until", None)
            for key in ("ambiguity_reason", "blocked_at", "retry_at", "retry_count"):
                plan.pop(key, None)
            if plan["status"] != "PENDING":
                return "CLOSED", plan
            if plan["entry_reached"]:
                weights = CandleSimulation()._norm_partial_weights(plan)
                remaining = 1 - sum(weights[i-1] for i in plan.get("tps_hit", []))
                sign = 1 if plan["direction"] == "LONG" else -1
                plan["open_r"] = sign * (candle.close - plan["entry"]) * remaining / abs(plan["entry"] - plan["stop_loss"])
                plan["mark_time"] = stamp + BAR
            if recovered or refined or (not history and stamp == last_available):
                break
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        if not plan.get("verified_until"):
            plan.pop("parent_prices", None)
        plan.pop("open_r", None)
        plan["blocked_at"] = next_bar(plan)
        plan["ambiguity_reason"] = str(exc) if isinstance(exc, EvidenceMissing) else f"Gate.io geçmiş verisi alınamadı ({type(exc).__name__})"
        if history:
            attempts = plan.get("retry_count", 0) + 1
            plan["retry_count"] = attempts
            plan["manual_review"] = attempts >= 6
            plan["retry_at"] = now + MINUTE * 2 ** (attempts - 1)
        return "AMBIGUOUS", plan
    return ("ACTIVE" if plan["entry_reached"] else "WAITING"), plan


def save(conn, symbol, row, result):
    chat, revision, state, raw = row
    new_state, plan = result
    updated = conn.execute("UPDATE chat_plans SET state=?,payload=? WHERE chat=? AND symbol=? AND revision=? AND state=? AND payload=?",
                           (new_state, json.dumps(plan), chat, symbol, revision, state, raw))
    if not updated.rowcount:
        return
    old = json.loads(raw)
    def record(kind, message):
        event(conn, chat, symbol, revision, kind, message, plan)
    if plan["entry_reached"] and not old.get("entry_reached_at"):
        record("ENTRY", "Sinyal takibi: giriş seviyesi görüldü.")
    for level in sorted(set(plan.get("tps_hit", [])) - set(old.get("tps_hit", []))):
        record(f"TP{level}", f"Sinyal takibi: TP{level} alındı.")
    if plan["status"] == "SL":
        record("STOP", "Sinyal takibi: stop görüldü.")
    if new_state == "CLOSED":
        record("CLOSED", f"Sinyal kapandı | {plan['realized_r']:+.2f}R")
    if new_state == "AMBIGUOUS" and state != new_state:
        record(f"VERIFY_{plan['blocked_at']}", "DOĞRULAMA BEKLİYOR — " + plan["ambiguity_reason"])
    if state == "AMBIGUOUS" and new_state in {"WAITING", "ACTIVE"}:
        record(f"VERIFIED_{old.get('blocked_at', next_bar(old))}", "Geçmiş doğrulandı, sinyal takibi sürüyor.")
