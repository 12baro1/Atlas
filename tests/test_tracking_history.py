import json
from unittest.mock import Mock

import pytest

from core.candle import Candle
from opportunity_pool import OpportunityPool
from telegram_tracking import evaluate
from tests.test_scan_virtual_portfolio import BTC, observation
from tracking_history import BAR, MINUTE, EvidenceMissing, TrackingHistory, TradeGroup

START = 1795140900000


def plan(**values):
    return dict(dict(opened_at=START-BAR, entry=100, stop_loss=90, tp1=110, tp2=120, tp3=130,
                     direction="LONG", symbol=BTC, entry_reached=True, entry_reached_at=START-1,
                     status="PENDING", payload={"execution_costs": {"entry_type": "LIMIT"}}), **values)


def bar(t, o, h, l, c, volume=1):
    return Candle(t, o, h, l, c, volume)


def test_missing_unclosed_duplicate_out_of_order_and_no_exit_before_entry():
    raw = json.dumps(plan(entry_reached=False))
    first = bar(START, 117, 120, 113, 116)
    late = bar(START+2*BAR, 100, 101, 99, 100)
    state, p = evaluate(BTC, "WAITING", raw, START+3*BAR, [late, first, first])
    assert state == "AMBIGUOUS" and p["blocked_at"] == START+BAR
    assert not p["entry_reached"] and not p.get("tps_hit")
    assert evaluate(BTC, state, json.dumps(p), START+BAR+1, [late]) is None
    conflict = bar(START, 117, 121, 113, 116)
    assert evaluate(BTC, "WAITING", raw, START+BAR, [first, conflict])[1]["blocked_at"] == START


def test_1m_orders_tp_before_trailing_stop_and_ignores_later_original_stop():
    parent = bar(START, 105, 112, 89, 96, 5)
    minutes = [bar(START, 105, 112, 104, 111), bar(START+MINUTE, 111, 111, 89, 96)]
    minutes.extend(bar(START+i*MINUTE, 96, 96, 96, 96) for i in (2, 3, 4))
    history = Mock()
    history.candles.side_effect = lambda symbol, start, width, count: {BAR:[parent], MINUTE:minutes}[width]
    state, p = evaluate(BTC, "ACTIVE", json.dumps(plan()), START+BAR, history=history)
    assert (state, p["status"], p["tps_hit"], p["trailing_stop"]) == ("CLOSED", "SL", [1], 100)
    assert p["resolved_at"] == START+2*MINUTE
    history.ticks.assert_not_called()


def test_historical_trades_required_for_same_minute_entry_and_tp():
    parent = bar(START, 105, 112, 99, 111, 5)
    history = Mock()
    def candles(symbol, start, width, count):
        return [parent] + [bar(start+i*width, 111, 111, 111, 111, 0) for i in range(1,count)]
    history.candles.side_effect = candles
    raw = json.dumps(plan(entry_reached=False))
    history.ticks.side_effect = EvidenceMissing("işlem geçmişi eksik")
    state, p = evaluate(BTC, "WAITING", raw, START+BAR, history=history)
    assert state == "AMBIGUOUS" and not p["entry_reached"] and not p.get("tps_hit")
    history.ticks.side_effect = None
    history.ticks.return_value = [TradeGroup(START+i, {x}, 1) for i,x in enumerate([105,100,99,112,111])]
    state, p = evaluate(BTC, state, json.dumps(p), p["retry_at"], history=history)
    assert state == "ACTIVE" and p["tps_hit"] == [1]


def test_waiting_entry_stays_visible_and_resumes_after_repeated_missing_prices(tmp_path, monkeypatch):
    import time
    import opportunity_pool
    from tests.test_scan_virtual_portfolio import service

    clock = [START-BAR]
    monkeypatch.setattr(time, "time", lambda: clock[0]/1000)
    path = tmp_path/"pool"
    pool = OpportunityPool(base_path=path, auto_persist=False)
    pool.tracking.follow_analysis("1", observation())
    history = Mock()
    history.candles.return_value = []
    clock[0] = START+BAR
    try:
        for _ in range(4):
            pool.tracking.advance_tracking(BTC, history=history)
            _, _, state, pending = pool.tracking.tracked("1")[0]
            assert state == "AMBIGUOUS" and not pending["entry_reached"]
            assert not pool.tracking.open_symbols()
            clock[0] = pending["retry_at"]
        pool.stop()
        pool = OpportunityPool(base_path=path, auto_persist=False)
        monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
        bot = service("1")
        report = bot.handle_islemler()
        assert "BTC" in report and "GİRİŞ BEKLEYENLER" in report and "Sonraki kontrol" in report
        assert "DOĞRULAMA BEKLİYOR" not in report
        assert not pool.tracking.pending_notifications("1")
        assert pool.tracking.open_symbols() == [BTC]

        history.candles.side_effect = lambda symbol, start, width, count: [
            bar(start+i*width, 50000, 50100, 49900, 50010) for i in range(count)
        ]
        clock[0] = pending["retry_at"]
        pool.tracking.advance_tracking(BTC, history=history)
        report = bot.handle_islemler()
        assert "AÇIK İŞLEMLER" in report
        assert sum("giriş seviyesi" in text for _, text in pool.tracking.pending_notifications("1")) == 1
    finally:
        pool.stop()


def test_gate_futures_wire_format_and_fractional_epoch_seconds(monkeypatch):
    history = TrackingHistory()
    get = Mock(side_effect=[
        [dict(o="0.0977", v=66, t=1795140900, c="0.09768", l="0.09751", h="0.09772", sum="644.4")],
        [dict(id=5923080, contract="CAP_USDT", create_time_ms=1795140954.218, size=-2, price="0.09768")],
    ])
    monkeypatch.setattr(history.exchange, "_get", get)
    assert history.candles("CAP/USDT:USDT", START, MINUTE, 1) == [bar(START,.0977,.09772,.09751,.09768,66)]
    assert history.ticks("CAP/USDT:USDT", START)[0].time == 1795140954218
    assert get.call_args.args[1] == {"contract":"CAP_USDT","from":1795140900,"to":1795140959,"limit":1000}


@pytest.mark.parametrize(("position", "candle"), [
    (plan(entry_reached_at=START+100), bar(START, 100, 106, 98, 105)),
    (
        plan(direction="SHORT", stop_loss=110, tp1=90, tp2=80, tp3=70,
             tps_hit=[1], trailing_stop=100, realized_r=0.5),
        bar(START, 91, 95, 89, 92),
    ),
])
def test_closed_five_minute_bar_without_exit_levels_needs_no_lower_candles(position, candle):
    history = Mock()
    history.candles.side_effect = [[candle], EvidenceMissing("Alt mum geçmişi eksik")]
    tracked = dict(position, verified_until=START + MINUTE, next_bar_time=START)
    state, result = evaluate(BTC, "ACTIVE", json.dumps(tracked), START+BAR, history=history)

    assert state == "ACTIVE"
    assert result["next_bar_time"] == START + BAR
    assert result.get("tps_hit") == tracked.get("tps_hit")
    assert result.get("realized_r") == tracked.get("realized_r")
    assert "ambiguity_reason" not in result
    history.candles.assert_called_once_with(BTC, START, BAR, 1)
    history.ticks.assert_not_called()


def test_partial_verification_survives_missing_later_ticks_and_restart():
    first = bar(START, 105, 112, 104, 111)
    second = bar(START+MINUTE, 111, 121, 99, 111)
    third = bar(START+2*MINUTE, 111, 111, 111, 111)
    parent = bar(START, 105, 121, 99, 111, 3)
    history = Mock()
    def candles(symbol, start, width, count):
        if width == BAR:
            return [parent]
        return [first, second, third] + [bar(start+i*width, 111,111,111,111,0) for i in (3,4)]
    history.candles.side_effect = candles
    history.ticks.side_effect = EvidenceMissing("işlem geçmişi eksik")
    state, p = evaluate(BTC, "ACTIVE", json.dumps(plan()), START+BAR, history=history)
    assert state == "AMBIGUOUS" and p["tps_hit"] == [1] and p["verified_until"] == second.time
    before = p["realized_r"]
    state, p = evaluate(BTC, state, json.dumps(p), p["retry_at"], history=history)
    assert state == "AMBIGUOUS" and p["realized_r"] == before and p["retry_count"] == 2


def test_missing_parent_rebuilt_from_complete_children():
    history = Mock()
    children = [bar(START+i*MINUTE, 105,106,104,105) for i in range(5)]
    history.candles.side_effect = [[], children[::-1]]
    state, p = evaluate(BTC, "WAITING", json.dumps(plan(entry_reached=False)), START+BAR, history=history)
    assert state == "WAITING" and p["next_bar_time"] == START+BAR


def test_legacy_unverified_entry_is_replayed_as_waiting():
    history = Mock()
    history.candles.return_value = [bar(START, 115,116,114,115)]
    state, p = evaluate(BTC, "AMBIGUOUS", json.dumps(plan(entry_reached_at=None)), START+BAR, history=history)
    assert state == "WAITING" and not p["entry_reached"] and not p.get("tps_hit")


def test_worker_recovers_delayed_data_and_updates_telegram_once(tmp_path, monkeypatch):
    import time
    import opportunity_pool
    from daily_refresh import DailyPoolRefresh
    from tests.test_scan_virtual_portfolio import service

    clock = [START-BAR]
    monkeypatch.setattr(time, "time", lambda: clock[0]/1000)
    pool = OpportunityPool(base_path=tmp_path/"pool", auto_persist=False)
    monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
    bot = service()
    pool.tracking.follow_analysis(bot.chat_id, observation())
    history = Mock()
    monkeypatch.setattr("tracking_history.TrackingHistory", lambda: history)
    worker = DailyPoolRefresh(pool, None, None, continuous=True)
    clock[0] = START+BAR
    try:
        history.candles.side_effect = TimeoutError()
        worker.refresh_virtual_positions()
        report = bot.handle_islemler()
        assert "GİRİŞ BEKLEYENLER" in report and "Son takip kontrolü" in report
        assert "DOĞRULAMA BEKLİYOR" not in report
        assert not pool.tracking.pending_notifications(bot.chat_id)
        assert pool.tracking.tracked(bot.chat_id)[0][3]["history_checked_at"] == clock[0]
        history.candles.side_effect = None
        history.candles.return_value = [bar(START, 50000, 50100, 49900, 50010)]
        clock[0] += MINUTE
        worker.refresh_virtual_positions()
        assert "AÇIK İŞLEMLER" in bot.handle_islemler()
        messages = pool.tracking.pending_notifications(bot.chat_id)
        assert sum("giriş seviyesi" in text for _, text in messages) == 1
        assert not any("Geçmiş doğrulandı" in text for _, text in messages)
        worker.refresh_virtual_positions()
        assert pool.tracking.pending_notifications(bot.chat_id) == messages

        clock[0] = START + 2 * BAR
        history.candles.side_effect = TimeoutError()
        worker.refresh_virtual_positions()
        report = bot.handle_islemler()
        assert "DOĞRULAMA BEKLİYOR" in report
        messages = pool.tracking.pending_notifications(bot.chat_id)
        assert sum("DOĞRULAMA BEKLİYOR" in text for _, text in messages) == 1
    finally:
        pool.stop()


def test_tied_prices_only_block_order_dependent_outcomes(monkeypatch):
    from telegram_tracking import resolve_bar
    import pytest

    history = TrackingHistory()
    def replay(prices, already_entered):
        rows = [dict(create_time_ms=START+t, price=p, size=1, id=i) for i,(t,p) in enumerate(prices)]
        monkeypatch.setattr(history, "_get", lambda *args, **kwargs: rows[::-1])
        history.ticks.cache_clear()
        values = [price for _,price in prices]
        candle = bar(START, values[0], max(values), min(values), values[-1], len(values))
        result = plan(entry_reached=already_entered)
        resolve_bar(result, BTC, candle, MINUTE, history, START+MINUTE)
        return result

    # Mixed prices both before and after a known entry. The next timestamp hits TP1.
    resolved = replay([(0,105),(0,106),(1,100),(2,111),(2,112)], False)
    assert resolved["entry_reached_at"] == START+1 and resolved["tps_hit"] == [1]
    # A tie after the proved stop cannot cancel the outcome.
    assert replay([(0,105),(1,90),(2,115),(2,116)], True)["status"] == "SL"
    with pytest.raises(EvidenceMissing, match="seviyelerinin sırası"):
        replay([(0,105),(1,90),(1,112),(2,106)], True)
    with pytest.raises(EvidenceMissing, match="atladı"):
        replay([(0,105),(1,99),(1,102),(2,112)], False)


def test_old_tie_review_reopens_once_without_losing_progress(tmp_path):
    from pool_store import PoolStore

    store = PoolStore(str(tmp_path))
    p = plan(ambiguity_reason="Aynı milisaniyede farklı işlem fiyatları", manual_review=False,
             retry_count=2, retry_at=START, next_bar_time=START, verified_until=START+1, tps_hit=[1])
    with store._transaction() as conn:
        conn.execute("INSERT INTO chat_plans VALUES(?,?,?,?,?,?)", ("c", BTC, 1, "setup", "AMBIGUOUS", json.dumps(p)))
    store.close()
    store = PoolStore(str(tmp_path))
    assert store.open_symbols() == [BTC]
    reopened = store.tracked("c")[0][3]
    assert reopened["retry_count"] == 2
    assert reopened["verified_until"] == START+1 and reopened["tps_hit"] == [1]
    reopened.update(manual_review=True, retry_count=6, ambiguity_reason="Aynı milisaniyede işlem seviyelerinin sırası doğrulanamadı")
    with store._transaction() as conn:
        conn.execute("UPDATE chat_plans SET payload=?", (json.dumps(reopened),))
    store.close()
    store = PoolStore(str(tmp_path))
    assert not store.open_symbols()
    assert store.tracked("c")[0][2] == "UNVERIFIED"
    store.close()


@pytest.mark.parametrize("finish", ["TP3", "SL"])
def test_background_worker_continues_targets_after_tp1_and_restart(tmp_path, monkeypatch, finish):
    import opportunity_pool
    from tests.test_scan_virtual_portfolio import service
    import time
    from daily_refresh import DailyPoolRefresh

    clock = [START-BAR]
    monkeypatch.setattr(time, "time", lambda: clock[0]/1000)
    path = tmp_path / "restart-after-tp1"
    pool = OpportunityPool(base_path=path, auto_persist=False)
    history = Mock()
    monkeypatch.setattr("tracking_history.TrackingHistory", lambda: history)
    def refresh(offset, low, high):
        stamp = START + offset * BAR
        price = (low + high) / 2
        clock[0] = stamp + BAR
        history.candles.return_value = [bar(stamp, price, high, low, price)]
        DailyPoolRefresh(pool, None, None, continuous=True).refresh_virtual_positions()
        history.candles.assert_called_with(BTC, stamp, BAR, 1)
        return pool.tracking.tracked("chat")[0]

    try:
        pool.tracking.follow_analysis("chat", observation())
        assert refresh(0, 49999, 50050)[2] == "ACTIVE"
        assert refresh(1, 50500, 51100)[3]["tps_hit"] == [1]
        pool.stop()
        pool = OpportunityPool(base_path=path, auto_persist=False)
        assert BTC in pool.tracking.open_symbols()
        assert refresh(2, 51500, 52100)[3]["tps_hit"] == [1, 2]
        state = refresh(3, 52500, 53100) if finish == "TP3" else refresh(3, 50500, 51200)
        assert state[2] == "CLOSED" and state[3]["status"] == finish
        monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
        bot = service("chat")
        bot._api = Mock(return_value={"message_id": 42, "chat": {"id": "chat"}})
        bot._deliver_notifications()
        bot._deliver_notifications()
        messages = [call.args[1]["text"] for call in bot._api.call_args_list]
        expected = ["TP1 alındı", "TP2 alındı", "TP3 alındı" if finish == "TP3" else "stop görüldü"]
        for event in expected:
            assert sum(event in message for message in messages) == 1
        assert not pool.tracking.pending_notifications("chat")
    finally:
        pool.stop()


@pytest.mark.parametrize("recovers", [False, True])
def test_background_checks_same_uncertain_position_up_to_three_times(recovers):
    import threading
    from telegram_tracking import evaluate_with_rechecks

    history = Mock()
    candle = bar(START, 105, 108, 102, 106)
    missing = EvidenceMissing("Alt mum geçmişi eksik")
    history.candles.side_effect = [missing, [candle]] if recovers else [missing] * 3

    now = START + BAR
    state, tracked = evaluate_with_rechecks(BTC, "ACTIVE", json.dumps(plan()), now, history, threading.Event())
    attempts = 2 if recovers else 3
    assert history.candles.call_count == attempts
    assert all(call.args == (BTC, START, BAR, 1) for call in history.candles.call_args_list)
    assert history.clear_cached_evidence.call_count == attempts - 1
    if recovers:
        assert state == "ACTIVE" and tracked["next_bar_time"] == START + BAR
        assert "retry_at" not in tracked
    else:
        assert state == "AMBIGUOUS" and tracked["retry_at"] == now + 15 * MINUTE


def test_background_rechecks_respect_exchange_rate_limit():
    import threading
    import requests
    from telegram_tracking import evaluate_with_rechecks

    response = requests.Response()
    response.status_code = 429
    history = Mock()
    history.candles.side_effect = requests.HTTPError(response=response)
    state, tracked = evaluate_with_rechecks(
        BTC, "ACTIVE", json.dumps(plan()), START + BAR, history, threading.Event()
    )
    assert state == "AMBIGUOUS" and tracked["network_failures"] == 1
    history.candles.assert_called_once()
    history.clear_cached_evidence.assert_not_called()


def test_confirmed_open_position_without_tp_survives_missing_history():
    history = Mock()
    history.candles.return_value = []
    p = plan(retry_count=2)
    state, pending = evaluate(BTC, "ACTIVE", json.dumps(p), START + BAR, history=history)
    assert state == "AMBIGUOUS"
    assert pending["status"] == "PENDING"
    assert pending["entry_reached_at"] == p["entry_reached_at"]
    assert pending["retry_at"] > START + BAR


def test_repeated_transport_timeouts_after_tp1_do_not_archive_then_stop():
    import requests
    history = Mock()
    history.candles.side_effect = requests.ReadTimeout()
    p = plan(tps_hit=[1], trailing_stop=100)
    now = START + BAR
    state = "ACTIVE"
    for failure in range(1, 7):
        state, p = evaluate(BTC, state, json.dumps(p), now, history=history)
        assert state == "AMBIGUOUS" and p["status"] == "PENDING"
        assert p["network_failures"] == failure and p.get("retry_count", 0) == 0
        assert p["tps_hit"] == [1] and history.candles.call_args.args[1] == START
        now = p["retry_at"]
    history.candles.side_effect = None
    history.candles.return_value = [bar(START,105,108,99,102)]
    state, p = evaluate(BTC, state, json.dumps(p), now, history=history)
    assert (state, p["status"], p["tps_hit"]) == ("CLOSED", "SL", [1])


def test_bnb_short_keeps_partial_position_until_verified_stop(tmp_path, monkeypatch):
    import time
    from pool_store import PoolStore
    from telegram_tracking import VERIFICATION_BACKOFF_THRESHOLD

    symbol = "BNB/USDT:USDT"
    clock = [START + BAR]
    monkeypatch.setattr(time, "time", lambda: clock[0] / 1000)
    original = plan(
        symbol=symbol, direction="SHORT", strategy="SMC", strategy_id="smc",
        stop_loss=110, tp1=90, tp2=80, tp3=70, tps_hit=[1], trailing_stop=100,
        realized_r=0.5, partial_weights=[0.5, 0.3, 0.2],
    )
    history = Mock()
    history.candles.return_value = []
    store = PoolStore(str(tmp_path))
    with store._transaction() as conn:
        conn.execute("INSERT INTO chat_follows VALUES(?,?,?)", ("chat", symbol, 1))
        conn.execute("INSERT INTO chat_plans VALUES(?,?,?,?,?,?)",
                     ("chat", symbol, 1, "old-short", "ACTIVE", json.dumps(original)))

    for _ in range(VERIFICATION_BACKOFF_THRESHOLD + 1):
        store.advance_tracking(symbol, history=history)
        _, _, state, remainder = store.tracked("chat")[0]
        assert state == "AMBIGUOUS" and remainder["tps_hit"] == [1]
        clock[0] = remainder["retry_at"]
    row = observation(symbol, stamp=clock[0])
    store.follow_analysis("chat", row)
    assert [(row[1], row[2]) for row in store.tracked("chat")] == [(1, "AMBIGUOUS")]
    store.close()

    store = PoolStore(str(tmp_path))
    try:
        assert store.tracked("chat")[0][2] == "AMBIGUOUS"
        history.candles.side_effect = lambda _, start, width, count: [
            bar(start, 85, 88, 79, 82), bar(start + width, 82, 91, 81, 90)
        ]
        store.advance_tracking(symbol, history=history)
        _, _, state, closed = store.tracked("chat")[0]
        assert (state, closed["status"], closed["tps_hit"]) == ("CLOSED", "SL", [1, 2])
        messages = [message for _, message in store.pending_notifications("chat")]
        assert any("TP2 alındı" in message for message in messages)
        assert any("stop görüldü" in message for message in messages)
        store.follow_analysis("chat", dict(row, observed=row["observed"] + 1))
        assert [(row[1], row[2]) for row in store.tracked("chat")] == [(2, "WAITING"), (1, "CLOSED")]
    finally:
        store.close()


@pytest.mark.parametrize("reason", [
    "Gate.io geçmiş verisi alınamadı (ReadTimeout)",
    "5m geçmişinde eksik veya çelişkili mum",
])
@pytest.mark.parametrize(("entered", "hits"), [(False, []), (True, [1])])
def test_only_current_unmuted_archive_reopens(tmp_path, reason, entered, hits):
    from pool_store import PoolStore
    from telegram_tracking import entry_confirmed

    store = PoolStore(str(tmp_path))
    archived = plan(entry_reached=entered, entry_reached_at=None, tps_hit=hits, trailing_stop=100,
                    status="UNVERIFIED", retry_count=3, resolved_at=START, ambiguity_reason=reason)
    with store._transaction() as conn:
        conn.executemany("INSERT INTO chat_follows VALUES(?,?,?)", [("c", BTC, 2), ("muted", BTC, 1)])
        conn.execute("INSERT INTO chat_tracking_preferences VALUES(?,?,1,?,0)", ("muted", BTC, START))
        conn.executemany(
            "INSERT INTO chat_plans VALUES(?,?,?,?,?,?)",
            [(chat, BTC, revision, "setup", "UNVERIFIED", json.dumps(archived))
             for chat, revision in (("c", 1), ("c", 2), ("muted", 1))],
        )
    store.close()
    store = PoolStore(str(tmp_path))
    try:
        current, old = store.tracked("c")
        assert current[2] == "AMBIGUOUS" and current[3]["tps_hit"] == hits
        assert entry_confirmed(current[3]) is entered
        assert current[3]["status"] == "PENDING" and BTC in store.open_symbols()
        assert old[2] == "UNVERIFIED"
        assert store.tracked("muted")[0][2] == "UNVERIFIED"
    finally:
        store.close()


@pytest.mark.parametrize("direction", ["SHORT", "LONG"])
def test_previous_day_closed_targets_observed_without_changing_fill_or_pnl(tmp_path, monkeypatch, direction):
    import time
    import telegram_command_service as telegram
    from types import SimpleNamespace
    from pool_store import PoolStore
    from tests.test_scan_virtual_portfolio import service

    clock = [START + 86400000]
    monkeypatch.setattr(time, "time", lambda: clock[0]/1000)
    class ReportDateTime(telegram.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(clock[0] / 1000, tz)

    monkeypatch.setattr(telegram, "datetime", ReportDateTime)
    store = PoolStore(str(tmp_path))
    closed = plan(direction=direction, strategy="test", resolved_at=START+1, tps_hit=[1],
                  status="SL", hit_sl=True, realized_r=0.3)
    if direction == "SHORT":
        closed.update(tp1=90, tp2=80, tp3=70)
    with store._transaction() as conn:
        conn.execute("INSERT INTO chat_plans VALUES('c','BNB',1,'setup','CLOSED',?)", (json.dumps(closed),))
        # Simulate a database from a release before post-exit tracking.
        conn.execute("DELETE FROM pool_meta WHERE key='post_exit_watch_seeded'")
    store.close()
    store = PoolStore(str(tmp_path))
    try:
        history = Mock()
        history.ticks.return_value = [TradeGroup(START, {closed["tp3"]}, 1), TradeGroup(START+2, {100}, 1)]
        store.refresh_closed_targets(history)
        assert store.tracked("c")[0][3]["post_exit_hits"] == []
        clock[0] += MINUTE
        price = closed["tp3"]
        history.candles.return_value = [bar(START+MINUTE, price,price,price,price)]
        store.refresh_closed_targets(history)
        clock[0] += MINUTE
        store.refresh_closed_targets(history)
        clock[0] += 2 * MINUTE
        store.refresh_closed_targets(history)
        record = store.tracked("c")[0]
        assert record[2] == "CLOSED" and record[3]["post_exit_hits"] == [2, 3]
        assert record[3]["tps_hit"] == [1] and record[3]["realized_r"] == 0.3
        assert record[3]["post_exit_incomplete"] and not store.pending_notifications("c")
        monkeypatch.setattr(telegram, "get_opportunity_pool", lambda: SimpleNamespace(tracking=store))
        report = service("c").handle_islemler()
        assert "TP1 alındı · Stop · +0.30R" in report
        assert "Kapanıştan sonra fiyat: TP2, TP3" in report
        clock[0] += BAR
        store.refresh_closed_targets(history)
        assert history.candles.call_count == 3
    finally:
        store.close()


def test_live_trades_advance_before_bar_closes_and_resume_after_restart(tmp_path, monkeypatch):
    import threading
    import time
    from pool_store import PoolStore

    clock = [START + 9_000]
    monkeypatch.setattr(time, "time", lambda: clock[0] / 1000)
    store = PoolStore(str(tmp_path))
    raw = json.dumps(plan(entry_reached=False, entry_reached_at=None, next_bar_time=START))
    with store._transaction() as conn:
        conn.execute("INSERT INTO chat_plans VALUES('chat',?,1,'setup','WAITING',?)", (BTC, raw))
    feed = Mock()
    stop = threading.Event()
    feed.trade_range.return_value = [TradeGroup(START+t, {p}, 1) for t, p in
                                     [(100, 115), (200, 100), (300, 111), (400, 121)]]
    store.refresh_live_trades(feed, stop)
    feed.trade_range.assert_called_once_with(BTC, START, START+7000)
    assert store.tracked("chat")[0][3]["tps_hit"] == [1, 2]
    store.close()
    store = PoolStore(str(tmp_path))
    try:
        clock[0] += 5000
        feed.trade_range.return_value += [TradeGroup(START+8000, {109}, 1),
                                         TradeGroup(START+9000, {131}, 1)]
        store.refresh_live_trades(feed, stop)
        store.refresh_live_trades(feed, stop)
        _, _, state, result = store.tracked("chat")[0]
        assert (state, result["status"], result["tps_hit"]) == ("CLOSED", "SL", [1, 2])
        events = [r[0] for r in store._thread_conn().execute("SELECT event FROM chat_events ORDER BY id")]
        assert events == ["ENTRY", "TP1", "TP2", "STOP", "CLOSED"]
    finally:
        store.close()


def test_live_tied_stop_and_target_preserve_verified_prefix_for_history():
    from telegram_tracking import evaluate_live
    rows = [TradeGroup(START+1, {111}, 1), TradeGroup(START+2, {95, 121}, 2)]
    state, result = evaluate_live(BTC, "ACTIVE", json.dumps(plan()), START+5000, lambda *args: rows)
    assert (state, result["tps_hit"], result["verified_until"]) == ("ACTIVE", [1], START+2)
    assert evaluate_live(BTC, state, json.dumps(result), START+9000, lambda *args: rows) is None
    assert evaluate(BTC, state, json.dumps(result), START+BAR, [bar(START,100,121,95,121)]) is None


def test_live_tracking_can_confirm_entry_after_publication_inside_an_open_candle():
    from telegram_tracking import evaluate_live
    opened = START + MINUTE
    raw = json.dumps(plan(opened_at=opened, entry_reached=False, entry_reached_at=None))
    read = Mock(return_value=[TradeGroup(opened-1, {100}, 1), TradeGroup(opened+100, {100}, 1)])
    assert evaluate_live(BTC, "WAITING", raw, opened+1000, read) is None
    read.assert_not_called()
    state, result = evaluate_live(BTC, "WAITING", raw, opened+4000, read)
    assert state == "ACTIVE" and result["entry_reached_at"] == opened+100


def test_pinned_legacy_parent_finishes_before_switching_to_five_minutes():
    span = 15 * MINUTE
    prefix = plan(tps_hit=[1], trailing_stop=100, realized_r=.3, verified_until=START+BAR,
                  last_processed_candle_time=START, next_bar_time=START, parent_prices=[111,112,105,111])
    history = Mock()
    history.candles.side_effect = [
        [bar(START,111,112,105,111,3)],
        [bar(START+i*BAR,111,112,105,111) for i in range(3)],
        [bar(START+span,111,121,111,120)]]
    state, result = evaluate(BTC, "AMBIGUOUS", json.dumps(prefix), START+span, history=history)
    assert result["next_bar_time"] == START+span and result["realized_r"] == .3
    state, result = evaluate(BTC, state, json.dumps(result), START+span+BAR, history=history)
    assert result["tps_hit"] == [1,2]
    assert [call.args[2] for call in history.candles.call_args_list] == [span, 5*MINUTE, 5*MINUTE]
