"""Chat-scoped theoretical signals. All transitions share the pool transaction."""
import json
import math
import time

import requests

from config import Config
from execution_costs import estimate_stop_cost
from core.candle import Candle
from tracking_history import BAR, MINUTE, TEN_SECONDS, QUARTER_HOUR, EvidenceMissing, indexed, matches, trades_match
from telegram_prices import confirmed_target_levels, tracked_levels
from trade_journal import TradeJournal


# Gate history and websocket backfill can lag behind 5m candle closure.
# Do not declare an unconfirmed entry permanently unverifiable in ~3 minutes.
# The retry schedule is bounded (up to 16m), preserving eventual termination.
MAX_VERIFICATION_ATTEMPTS = 8

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_follows(
 chat TEXT NOT NULL, symbol TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(chat,symbol));
CREATE TABLE IF NOT EXISTS chat_tracking_preferences(
 chat TEXT NOT NULL, symbol TEXT NOT NULL, muted INTEGER NOT NULL,
 changed_at INTEGER NOT NULL, suppress_through INTEGER NOT NULL,
 PRIMARY KEY(chat,symbol));
CREATE TABLE IF NOT EXISTS chat_plans(
 chat TEXT NOT NULL, symbol TEXT NOT NULL, revision INTEGER NOT NULL,
 setup_id TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(chat,symbol,revision));
CREATE INDEX IF NOT EXISTS chat_plan_state ON chat_plans(symbol,state);
CREATE TABLE IF NOT EXISTS post_exit_watch(
 chat TEXT NOT NULL, symbol TEXT NOT NULL, revision INTEGER NOT NULL,
 cursor_ms INTEGER NOT NULL, next_at INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0, hits TEXT NOT NULL DEFAULT '[]', incomplete INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(chat,symbol,revision));
CREATE INDEX IF NOT EXISTS post_exit_due ON post_exit_watch(done,next_at);
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
    _MOVE_STOP_TO_TP1_AT_TP2 = False  # Legacy switch; journal now moves to entry only after TP2.

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


def _same_trade_setup(previous, setup, previous_id):
    """Closed plans must not be reopened by republishing identical trade geometry."""
    if previous_id == setup.get("setup_id"):
        return True
    if previous.get("strategy_id") != setup.get("strategy_id"):
        return False
    if previous.get("direction") != setup.get("direction"):
        return False
    levels = (("entry", "entry_price"), ("stop_loss", "stop_loss"),
              ("tp1", "tp1"), ("tp2", "tp2"), ("tp3", "tp3"))
    try:
        return all(math.isclose(float(previous[old]), float(setup[new]),
                                rel_tol=1e-9, abs_tol=0.0)
                   for old, new in levels)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def transition(conn, chat, symbol, revision, setup, *, announce, user_requested=False):
    current = conn.execute("SELECT setup_id,state,payload FROM chat_plans WHERE chat=? AND symbol=? AND revision=?",
                           (chat, symbol, revision)).fetchone()
    if current:
        previous_id, state, raw = current
        old = json.loads(raw)
        if setup and previous_id == setup["setup_id"] and state not in {"INVALIDATED", "REMOVED"}:
            return
        if state in {"ACTIVE","AMBIGUOUS"}:
            # Do not silently replace an entered trade with a new pool setup.
            # Notify the follower once per distinct replacement instead.
            if setup and previous_id != setup["setup_id"] and announce:
                kind = "SETUP_CHANGED:" + str(setup["setup_id"])
                event(conn, chat, symbol, revision, kind,
                      "TAKİPTEKİ İŞLEMİN SETUP'I DEĞİŞTİ\\n"
                      "Mevcut giriş/stop/TP korunuyor; yeni havuz fırsatı otomatik işlem açmaz.",
                      old)
            return
        if state == "WAITING":
            old["resolved_at"] = int(time.time()*1000)
            conn.execute("UPDATE chat_plans SET state='INVALIDATED',payload=? WHERE chat=? AND symbol=? AND revision=?",
                         (json.dumps(old),chat, symbol, revision))
            if announce and not setup:
                event(conn, chat, symbol, revision, "INVALIDATED", "SETUP KALDIRILDI\nNeden: Strateji yapısı bozuldu. Yeni setup bekleniyor.", old)
    if not setup:
        return
    # Pool publications are informational. Only a user-requested command may
    # start tracking an untracked symbol or restart after a terminal plan.
    # A still-WAITING user-selected plan may be replaced as its setup evolves.
    if not user_requested and (not current or state != "WAITING"):
        return
    # A closed trade is immutable. Pool refreshes may publish a different ID
    # for the same geometry; neither must create another virtual entry.
    closed = conn.execute(
        "SELECT setup_id,payload FROM chat_plans WHERE chat=? AND symbol=? AND state='CLOSED'",
        (chat, symbol),
    ).fetchall()
    if any(_same_trade_setup(json.loads(raw), setup, previous_id)
           for previous_id, raw in closed):
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
        label = "YENİ SETUP" if not current or state in {"INVALIDATED","CLOSED","UNVERIFIED","REMOVED"} else "SETUP GÜNCELLENDİ"
        previous = f"\nEski: {old['direction']} | {old['strategy']}" if current else ""
        event(conn, chat, symbol, revision, "SETUP", f"{label}{previous}\nYeni: {outcome['direction']} | {outcome['strategy']}", outcome)


def watch_closed_targets(conn, chat, symbol, revision, plan):
    hits = confirmed_target_levels(plan)
    if not hits or 3 in hits or not plan.get("resolved_at"):
        return
    if not any(plan.get(f"tp{i}") for i in (2, 3) if i > max(hits)):
        return
    end = int(plan["resolved_at"])
    conn.execute("INSERT OR IGNORE INTO post_exit_watch(chat,symbol,revision,cursor_ms) "
                 "VALUES(?,?,?,?)", (chat, symbol, revision, end))


def next_bar(plan):
    if "next_bar_time" in plan:
        start = plan["next_bar_time"]
        if "parent_prices" not in plan:
            start = max(start, plan.get("verified_until", 0) // BAR * BAR)
        return start
    if "last_processed_candle_time" in plan:
        # Older plans with only this cursor already consumed the entire 15m bar.
        return (plan["last_processed_candle_time"] // QUARTER_HOUR + 1) * QUARTER_HOUR
    return (plan["opened_at"] // BAR + 1) * BAR


def _exit_levels_in_bar(plan, candle):
    long = plan["direction"] == "LONG"
    stop = plan.get("trailing_stop", plan["stop_loss"])
    targets = [plan[f"tp{i}"] for i in (1, 2, 3) if i not in plan.get("tps_hit", [])]
    touched = [price for price in targets if (candle.high >= price if long else candle.low <= price)]
    stopped = candle.low <= stop if long else candle.high >= stop
    return targets, touched, stopped


def _market_entry_risk_valid(plan, entry):
    """Recheck stop economics against the actual theoretical MARKET entry."""
    try:
        stop = float(plan["stop_loss"])
        entry = float(entry)
        planned = float(plan["entry"])
        if not all(math.isfinite(x) and x > 0 for x in (entry, stop, planned)):
            return False
        distance = abs(stop - entry)
        if distance <= 0 or distance / entry < float(getattr(Config, "MIN_STOP_PERCENT", 0.0005)):
            return False
        # A market reference cannot drift arbitrarily from the approved setup.
        if abs(entry - planned) / planned > float(getattr(Config, "MAX_MARKET_ENTRY_DISTANCE_PCT", 0.05)):
            return False
        costs = plan["payload"]["execution_costs"]
        stop_cost = estimate_stop_cost(
            entry, stop, entry_type="MARKET",
            maker_fee_rate=costs.get("maker_fee_rate", 0.0002),
            taker_fee_rate=costs.get("taker_fee_rate", 0.00055),
            spread_rate=costs.get("spread_rate", 0.0002),
            slippage_rate=costs.get("slippage_rate", 0.0003),
        )
        max_cost_r = float(getattr(Config, "MAX_STOP_EXECUTION_COST_R", 0.5))
        if max_cost_r <= 0 or stop_cost["total"] / distance > max_cost_r:
            return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return False


def apply_bar(plan, candle, width):
    """Return False without mutating the plan if OHLC cannot order its events."""
    if getattr(candle, "volume", None) == 0:
        plan["last_processed_candle_time"] = candle.time
        return True
    long = plan["direction"] == "LONG"
    stop = plan.get("trailing_stop", plan["stop_loss"])
    targets, touched, stopped = _exit_levels_in_bar(plan, candle)
    market = not plan["entry_reached"] and plan["payload"]["execution_costs"]["entry_type"] == "MARKET"
    entry = candle.open if market else plan["entry"]
    if not plan["entry_reached"]:
        if market:
            if not (stop < entry < targets[0] if long else stop > entry > targets[0]):
                return False
            if not _market_entry_risk_valid(plan, entry):
                plan.update(status="ENTRY_REJECTED", resolved_at=candle.time)
                return True
        elif not candle.low <= entry <= candle.high:
            plan["last_processed_candle_time"] = candle.time
            return True
        elif touched or stopped:
            return False

    if len(touched) > 1 and width > 1:
        return False
    if touched:
        entry_stop_touched = (plan["tp1"] in touched
                              and (candle.low <= entry if long else candle.high >= entry))
        if stopped or entry_stop_touched:
            return False
    if market:
        plan.update(entry=entry, entry_reached=True, entry_reached_at=candle.time)
    CandleSimulation().resolve_signal_outcome(plan, [candle])
    if plan["status"] != "PENDING":
        plan["resolved_at"] = candle.time + width
    return True


def resolve_bar(plan, symbol, candle, width, history, now):
    verified = max(plan["opened_at"], plan.get("verified_until", 0))
    if candle.time + width <= verified:
        return False
    if candle.time >= verified and apply_bar(plan, candle, width):
        plan["verified_until"] = candle.time + width
        return False
    if width == BAR and candle.time < verified:
        can_skip_tail = False
        if entry_confirmed(plan):
            _, touched, stopped = _exit_levels_in_bar(plan, candle)
            can_skip_tail = not touched and not stopped
        elif plan["payload"]["execution_costs"]["entry_type"] == "LIMIT":
            can_skip_tail = not candle.low <= plan["entry"] <= candle.high
        if can_skip_tail:
            # The complete range also bounds the unprocessed portion.
            plan["last_processed_candle_time"] = candle.time
            plan["verified_until"] = candle.time + width
            return False
    if history is None:
        raise EvidenceMissing("Mum içinde giriş, hedef veya stop sırası belirsiz")
    if width in (MINUTE, TEN_SECONDS):
        if width == MINUTE:
            # Gate futures publishes 10s candles. These can prove entry and
            # exit order within a conflicting 1m candle without downloading
            # thousands of individual fills. Verify the complete 1m aggregate
            # before trusting the subdivision; otherwise fall back to trades.
            try:
                fine = child_range(history, symbol, candle.time, MINUTE, TEN_SECONDS, now)
            except (EvidenceMissing, KeyError, TypeError, ValueError, AttributeError):
                fine = []
            if len(fine) == MINUTE // TEN_SECONDS and all(fine) and matches(candle, fine):
                for child in fine:
                    resolve_bar(plan, symbol, child, TEN_SECONDS, history, now)
                    if plan["status"] != "PENDING":
                        break
                return True
        children = (history.ticks(symbol, candle.time) if width == MINUTE
                    else history.trade_range(symbol, candle.time, candle.time + width))
        if not trades_match(candle, children):
            raise EvidenceMissing(
                f"İşlem geçmişi {width // 1000}s mumun fiyat ve hacmini doğrulamıyor"
            )
        previous_low = previous_high = candle.open
        for index, group in enumerate(children):
            low, high = min(group.prices), max(group.prices)
            entry = plan["entry"]
            skipped_entry = (entry not in group.prices
                             and min(previous_low, low) < entry < max(previous_high, high))
            previous_low, previous_high = low, high
            if group.time < verified:
                continue
            only_price = low if low == high else None
            first = candle.open if index == 0 else only_price
            last = candle.close if index == len(children) - 1 else only_price
            if not plan["entry_reached"]:
                market = plan["payload"]["execution_costs"]["entry_type"] == "MARKET"
                if market and first is None:
                    raise EvidenceMissing("Aynı milisaniyede piyasa giriş fiyatı doğrulanamadı")
                if not market and skipped_entry:
                    raise EvidenceMissing("İşlem fiyatları giriş seviyesini atladı")
            # Only the enclosing minute proves its endpoints. Inside a tied
            # group the simulator can use the range if event order is immaterial.
            tick = Candle(group.time, first, high, low, last, group.volume)
            if not apply_bar(plan, tick, 1):
                if low != high:
                    raise EvidenceMissing("Aynı milisaniyede işlem seviyelerinin sırası doğrulanamadı")
                raise EvidenceMissing("İşlem fiyatı plan seviyeleriyle uyuşmuyor")
            plan["verified_until"] = group.time + 1
            if plan["status"] != "PENDING":
                break
        return True
    for step in ((5 * MINUTE, MINUTE) if width == QUARTER_HOUR else (MINUTE,)):
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


def recover_missing_bar(history, symbol, start, now, span):
    for width in ((BAR, MINUTE) if span == QUARTER_HOUR else (MINUTE,)):
        children = child_range(history, symbol, start, span, width, now)
        if all(children):
            return Candle(start, children[0].open, max(c.high for c in children),
                          min(c.low for c in children), children[-1].close, sum(c.volume for c in children))
    raise EvidenceMissing(f"{span // MINUTE}m geçmişi eksik, alt mumlar aralığı tamamlamıyor")


def mark_position(plan, price, stamp):
    weights = CandleSimulation()._norm_partial_weights(plan)
    remaining = 1 - sum(weights[i-1] for i in plan.get("tps_hit", []))
    sign = 1 if plan["direction"] == "LONG" else -1
    plan["open_r"] = sign * (price - plan["entry"]) * remaining / abs(plan["entry"] - plan["stop_loss"])
    plan["mark_time"] = stamp


def evaluate_live(symbol, state, raw, now, read_trades):
    """Replay a completed slice of public trades; the open candle is never a fill."""
    plan = json.loads(raw)
    cursor = plan["opened_at"]
    if plan["entry_reached"] or any(
        key in plan for key in ("next_bar_time", "last_processed_candle_time", "verified_until")
    ):
        cursor = max(next_bar(plan), plan.get("verified_until", 0))
    # Leave two seconds for the exchange to publish trades. The historical
    # worker owns older gaps and ambiguous evidence.
    end = (now // 1000 - 2) * 1000
    if state not in {"ACTIVE", "WAITING"} or not 0 < end - cursor <= BAR:
        return
    start = cursor // 1000 * 1000
    try:
        groups = read_trades(symbol, start, end)
    except EvidenceMissing:
        return
    previous = plan.get("live_price")
    for group in groups:
        if group.time < cursor:
            continue
        low, high = min(group.prices), max(group.prices)
        price = low if low == high else None
        if not plan["entry_reached"]:
            entry = plan["entry"]
            if price is None and (low <= entry <= high or
                                  plan["payload"]["execution_costs"]["entry_type"] == "MARKET"):
                break
            if previous is not None and (previous < entry < low or high < entry < previous):
                break
        tick = Candle(group.time, price, high, low, price, group.volume)
        if not apply_bar(plan, tick, 1):
            break
        previous = price
        plan["verified_until"] = group.time + 1
        plan["next_bar_time"] = plan["verified_until"] // BAR * BAR
        plan["live_price"] = price
        if plan["status"] != "PENDING":
            return ("INVALIDATED" if plan["status"] == "ENTRY_REJECTED" else "CLOSED"), plan
    if plan.get("verified_until", 0) > cursor:
        if plan["entry_reached"] and previous is not None:
            mark_position(plan, previous, plan["verified_until"] - 1)
        elif previous is None:
            plan.pop("open_r", None)
        return ("ACTIVE" if plan["entry_reached"] else "WAITING"), plan


def evaluate(symbol, state, raw, now, candles=None, history=None):
    plan = json.loads(raw)
    if plan.get("manual_review") or plan.get("retry_at", 0) > now:
        return
    if history is None and plan.get("verified_until"):
        return
    start = next_bar(plan)
    if not plan["entry_reached"] and not any(
        key in plan for key in ("next_bar_time", "last_processed_candle_time", "verified_until")
    ) and plan["opened_at"] % BAR:
        # Resolve the signal's partial opening candle when live trades were unavailable.
        start = plan["opened_at"] // BAR * BAR
    width = plan.get("parent_width", QUARTER_HOUR) if "parent_prices" in plan else BAR
    count = min(1 if width == QUARTER_HOUR else 96, (now - start) // width)
    if count <= 0:
        return
    # Older code set entry_reached before proving the order and omitted its timestamp.
    if state == "AMBIGUOUS" and plan["entry_reached"] and not plan.get("entry_reached_at"):
        plan["entry_reached"] = False
    try:
        if history:
            plan["history_checked_at"] = now
            candles = history.candles(symbol, start, width, count)
        bars = indexed(candles or [], width, now)
        last_available = max(bars, default=0)
        if not history and last_available < start:
            return
        for stamp in range(start, start + count * width, width):
            candle = bars.get(stamp)
            recovered = False
            if candle is None:
                if history is None or stamp in bars:
                    raise EvidenceMissing(f"{width // MINUTE}m geçmişinde eksik veya çelişkili mum")
                candle = recover_missing_bar(history, symbol, stamp, now, width)
                recovered = True
            # Pin the parent while verified children advance the journal cursor.
            plan["next_bar_time"] = stamp
            prices = [candle.open, candle.high, candle.low, candle.close]
            if plan.get("parent_prices", prices) != prices:
                raise EvidenceMissing(f"Kısmen doğrulanmış {width // MINUTE}m mumun fiyatları değişti")
            plan["parent_width"] = width
            plan["parent_prices"] = prices
            refined = resolve_bar(plan, symbol, candle, width, history, now)
            plan["next_bar_time"] = stamp + width
            plan.pop("parent_prices")
            plan.pop("parent_width")
            plan.pop("verified_until", None)
            plan.pop("live_price", None)
            for key in ("ambiguity_reason", "blocked_at", "retry_at", "retry_count", "network_failures"):
                plan.pop(key, None)
            if plan["status"] != "PENDING":
                return ("INVALIDATED" if plan["status"] == "ENTRY_REJECTED" else "CLOSED"), plan
            if plan["entry_reached"]:
                mark_position(plan, candle.close, stamp + width)
            if recovered or refined or (not history and stamp == last_available):
                break
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        if not plan.get("verified_until"):
            plan.pop("parent_prices", None)
        plan.pop("open_r", None)
        plan["blocked_at"] = next_bar(plan)
        plan["ambiguity_reason"] = str(exc) if isinstance(exc, EvidenceMissing) else f"Gate.io geçmiş verisi alınamadı ({type(exc).__name__})"
        temporary = isinstance(exc, (TimeoutError, ConnectionError, requests.Timeout, requests.ConnectionError))
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            temporary = exc.response.status_code in {408, 429, 500, 502, 503, 504}
        if history and temporary:
            failures = plan.get("network_failures", 0) + 1
            plan["network_failures"] = failures
            plan["retry_at"] = now + MINUTE * 2 ** min(failures - 1, 4)
            return "AMBIGUOUS", plan
        if history:
            plan.pop("network_failures", None)
            attempts = plan.get("retry_count", 0) + 1
            plan["retry_count"] = min(attempts, MAX_VERIFICATION_ATTEMPTS)
            if attempts >= MAX_VERIFICATION_ATTEMPTS:
                if plan.get("entry_reached") and plan.get("entry_reached_at"):
                    # Missing history cannot establish an exit from the remaining position.
                    plan["retry_at"] = now + 15 * MINUTE
                    return "AMBIGUOUS", plan
                plan.pop("retry_at", None)
                plan.update(status="UNVERIFIED", resolved_at=now)
                return "UNVERIFIED", plan
            plan["retry_at"] = now + MINUTE * 2 ** (attempts - 1)
        return "AMBIGUOUS", plan
    return ("ACTIVE" if plan["entry_reached"] else "WAITING"), plan


def entry_confirmed(plan):
    return bool(plan.get("entry_reached") and plan.get("entry_reached_at"))


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
    confirmed = entry_confirmed(plan)
    was_confirmed = entry_confirmed(old)
    if confirmed and not was_confirmed:
        record("ENTRY", "Sinyal takibi: giriş seviyesi görüldü.")
    for level in sorted(set(plan.get("tps_hit", [])) - set(old.get("tps_hit", []))):
        record(f"TP{level}", f"Sinyal takibi: TP{level} alındı.")
    if plan["status"] == "SL":
        record("STOP", "Sinyal takibi: stop görüldü.")
    if new_state == "INVALIDATED" and plan.get("status") == "ENTRY_REJECTED":
        record("ENTRY_REJECTED", "MARKET giriş reddedildi: stop mesafesi veya işlem maliyeti güvenli değil.")
    if new_state == "CLOSED":
        watch_closed_targets(conn, chat, symbol, revision, plan)
        record("CLOSED", f"Sinyal kapandı | {plan['realized_r']:+.2f}R")
    if new_state == "UNVERIFIED" and not confirmed:
        record("ENTRY_UNVERIFIED", "GİRİŞ TAKİBİ SONLANDI — Fiyat geçmişinden giriş teyit edilemedi.")
    was_verifying_open_position = state == "AMBIGUOUS" and was_confirmed
    if confirmed and new_state == "AMBIGUOUS" and not was_verifying_open_position:
        record(f"VERIFY_{plan['blocked_at']}", "DOĞRULAMA BEKLİYOR — " + plan["ambiguity_reason"])
    if was_verifying_open_position and new_state == "ACTIVE":
        record(f"VERIFIED_{old.get('blocked_at', next_bar(old))}", "Geçmiş doğrulandı, sinyal takibi sürüyor.")
