"""Chat-scoped theoretical signals. All transitions share the pool transaction."""
import math
import json
import time

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


def event(conn, chat, symbol, revision, kind, message):
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
                event(conn, chat, symbol, revision, "INVALIDATED", "SETUP KALDIRILDI\nNeden: Strateji yapısı bozuldu. Yeni setup bekleniyor.")
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
        event(conn, chat, symbol, revision, "SETUP", f"{label}{previous}\nYeni: {outcome['direction']} | {outcome['strategy']}\nGiriş: {outcome['entry']} | Stop: {outcome['stop_loss']} | TP1: {outcome['tp1']} | TP2: {outcome['tp2']}")


def advance(conn, symbol, candles):
    simulator = CandleSimulation()
    rows = conn.execute("SELECT chat,revision,payload FROM chat_plans WHERE symbol=? AND state IN ('ACTIVE','WAITING')",
                        (symbol,)).fetchall()
    for chat, revision, raw in rows:
        outcome = json.loads(raw)
        entered = outcome["entry_reached"]
        previous = set(outcome.get("tps_hit", []))
        ambiguous = False
        for candle in candles:
            cursor = outcome.get("last_processed_candle_time", outcome["opened_at"])
            if candle.time <= cursor:
                continue
            if candle.time - cursor > 900000:
                ambiguous = True
                break
            long = outcome["direction"] == "LONG"
            stop = outcome.get("trailing_stop", outcome["stop_loss"])
            hit_stop = candle.low <= stop if long else candle.high >= stop
            remaining = [outcome[f"tp{i}"] for i in (1,2,3) if i not in outcome.get("tps_hit", [])]
            hit_targets = [t for t in remaining if (candle.high >= t if long else candle.low <= t)]
            if not outcome["entry_reached"]:
                market = outcome["payload"]["execution_costs"]["entry_type"] == "MARKET"
                if market:
                    fill = candle.open
                    if not (stop < fill < remaining[0] if long else stop > fill > remaining[0]):
                        ambiguous = True
                        break
                    outcome["entry"] = fill
                    outcome["entry_reached"] = True
                    outcome["entry_reached_at"] = candle.time
                elif not (candle.low <= outcome["entry"] <= candle.high):
                    outcome["last_processed_candle_time"] = candle.time
                    continue
                elif hit_targets or hit_stop:
                    outcome["entry_reached"] = True
                    ambiguous = True
                    break
            if outcome["entry_reached"] and hit_targets:
                level = max(i for i in (1,2,3) if outcome[f"tp{i}"] in hit_targets)
                moved = outcome["entry"] if level == 1 else outcome["tp1"]
                crosses_moved = candle.low <= moved if long else candle.high >= moved
                if hit_stop or (level < 3 and crosses_moved) or (len(hit_targets)>1 and crosses_moved):
                    ambiguous = True
                    break
            simulator.resolve_signal_outcome(outcome, [candle])
            if outcome["status"] != "PENDING":
                outcome["resolved_at"] = candle.time + 900000
                break
        if outcome["entry_reached"] and not entered:
            event(conn, chat, symbol, revision, "ENTRY", "Sinyal takibi: giriş seviyesi görüldü.")
        for level in sorted(set(outcome.get("tps_hit", [])) - previous):
            event(conn, chat, symbol, revision, f"TP{level}", f"Sinyal takibi: TP{level} alındı.")
        if candles and outcome["entry_reached"] and outcome["status"] == "PENDING":
            mark = candles[-1]
            if (mark.time >= outcome["opened_at"] and mark.time + 900000 >= outcome.get("mark_time", 0)
                    and math.isfinite(mark.close) and mark.close > 0):
                weights = simulator._norm_partial_weights(outcome)
                remaining = 1 - sum(weights[i-1] for i in outcome.get("tps_hit", []))
                sign = 1 if outcome["direction"] == "LONG" else -1
                risk = abs(outcome["entry"] - outcome["stop_loss"])
                outcome["open_r"] = sign * (mark.close - outcome["entry"]) * remaining / risk
                outcome["mark_time"] = mark.time + 900000
        status = outcome["status"]
        if status == "SL":
            event(conn, chat, symbol, revision, "STOP", "Sinyal takibi: stop görüldü.")
        if status != "PENDING":
            event(conn, chat, symbol, revision, "CLOSED", f"Sinyal kapandı | {outcome['realized_r']:+.2f}R")
        state = ("ACTIVE" if outcome["entry_reached"] else "WAITING") if status == "PENDING" else "CLOSED"
        if ambiguous:
            state = "AMBIGUOUS"
            outcome.pop("open_r", None)
            event(conn, chat, symbol, revision, "AMBIGUOUS", "Fiyat sırası veya mum geçmişi belirsiz. Sonuç hesaplanamadı.")
        conn.execute("UPDATE chat_plans SET state=?,payload=? WHERE chat=? AND symbol=? AND revision=?",
                     (state, json.dumps(outcome), chat, symbol, revision))
