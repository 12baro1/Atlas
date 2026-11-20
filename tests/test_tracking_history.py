import json
from unittest.mock import Mock

from core.candle import Candle
from opportunity_pool import OpportunityPool
from telegram_tracking import evaluate
from tests.test_scan_virtual_portfolio import BTC, observation
from tracking_history import BAR, MINUTE, EvidenceMissing, TrackingHistory

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
    parent = bar(START, 105, 112, 89, 96, 7)
    minutes = [bar(START, 105, 112, 104, 111), bar(START+MINUTE, 111, 111, 89, 96)]
    minutes.extend(bar(START+i*MINUTE, 96, 96, 96, 96) for i in (2, 3, 4))
    five = [bar(START, 105, 112, 89, 96, 5)] + [bar(START+i*MINUTE, 96, 96, 96, 96) for i in (5, 10)]
    history = Mock()
    history.candles.side_effect = lambda symbol, start, width, count: {BAR:[parent], 5*MINUTE:five, MINUTE:minutes}[width]
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
    history.ticks.return_value = [bar(START+i, x,x,x,x) for i,x in enumerate([105,100,99,112,111])]
    state, p = evaluate(BTC, state, json.dumps(p), p["retry_at"], history=history)
    assert state == "ACTIVE" and p["tps_hit"] == [1]


def test_delayed_backfill_and_restart_retains_retry_and_stops_polling(tmp_path, monkeypatch):
    import time
    clock = [START-BAR]
    monkeypatch.setattr(time, "time", lambda: clock[0]/1000)
    path = tmp_path/"pool"
    pool = OpportunityPool(base_path=path, auto_persist=False)
    pool.tracking.follow_analysis("1", observation())
    history = Mock()
    history.candles.return_value = []
    clock[0] = START+300*BAR
    pool.tracking.advance_tracking(BTC, history=history)
    assert history.candles.call_args_list[0].args == (BTC, START, BAR, 96)
    pool.stop()
    pool = OpportunityPool(base_path=path, auto_persist=False)
    try:
        for attempt in range(1,7):
            p = pool.tracking.tracked("1")[0][3]
            assert p["retry_count"] == attempt and p["blocked_at"] == START
            assert pool.tracking.open_symbols() == []
            clock[0] = p["retry_at"]
            if attempt != 6:
                assert pool.tracking.open_symbols() == [BTC]
                pool.tracking.advance_tracking(BTC, history=history)
        assert p["manual_review"] and pool.tracking.open_symbols() == []
        pool.tracking.advance_tracking(BTC, history=history)
        assert history.candles.call_count == 6 * 3
        assert len(pool.tracking.pending_notifications("1")) == 1
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


def test_partial_verification_survives_missing_later_ticks_and_restart():
    first = bar(START, 105, 112, 104, 111)
    second = bar(START+5*MINUTE, 111, 121, 99, 111)
    third = bar(START+10*MINUTE, 111, 111, 111, 111)
    parent = bar(START, 105, 121, 99, 111, 3)
    history = Mock()
    def candles(symbol, start, width, count):
        if width == BAR:
            return [parent]
        if width == 5*MINUTE:
            return [first, second, third]
        return [second] + [bar(start+i*width, 111,111,111,111,0) for i in range(1,count)]
    history.candles.side_effect = candles
    history.ticks.side_effect = EvidenceMissing("işlem geçmişi eksik")
    state, p = evaluate(BTC, "ACTIVE", json.dumps(plan()), START+BAR, history=history)
    assert state == "AMBIGUOUS" and p["tps_hit"] == [1] and p["verified_until"] == second.time
    before = p["realized_r"]
    state, p = evaluate(BTC, state, json.dumps(p), p["retry_at"], history=history)
    assert state == "AMBIGUOUS" and p["realized_r"] == before and p["retry_count"] == 2


def test_missing_parent_rebuilt_from_complete_children():
    history = Mock()
    children = [bar(START+i*5*MINUTE, 105,106,104,105) for i in range(3)]
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
        assert "DOĞRULAMA BEKLİYOR" in bot.handle_islemler()
        history.candles.side_effect = None
        history.candles.return_value = [bar(START, 50000, 50100, 49900, 50010)]
        clock[0] += MINUTE
        worker.refresh_virtual_positions()
        assert "Aktif" in bot.handle_islemler()
        messages = pool.tracking.pending_notifications(bot.chat_id)
        assert sum("giriş seviyesi" in text for _, text in messages) == 1
        worker.refresh_virtual_positions()
        assert pool.tracking.pending_notifications(bot.chat_id) == messages
    finally:
        pool.stop()
