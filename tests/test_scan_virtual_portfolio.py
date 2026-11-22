"""Public-cycle publication, chat isolation and virtual execution with offline market inputs."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import opportunity_pool
import telegram_command_service as telegram
from opportunity_pool import OpportunityPool
from scan_queue import ScanQueue
from scan_service import ScanService
from telegram_commands import TELEGRAM_COMMANDS
from tests.test_runtime_pool_integration import engine_shaped_result, make_runtime


BTC = "BTC/USDT:USDT"
DAY = 86_400_000


def observation(symbol=BTC, stamp=1, *, setup=True, broken=False):
    result = engine_shaped_result(symbol)
    candidate = make_runtime()._setup_to_candidate(result["strategy_lab"]["selected"], symbol)
    return dict(symbol=symbol, cutoff=stamp, observed=stamp,
                setup=candidate.to_dict() if setup else None,
                broken=[candidate.strategy_id] if broken else [])


@pytest.fixture
def pool(tmp_path, monkeypatch):
    value = OpportunityPool(base_path=tmp_path/"pool", auto_persist=False)
    monkeypatch.setattr(opportunity_pool, "_pool_instance", value)
    yield value
    value.stop()


def service(chat="-10"):
    return telegram.TelegramCommandService(MagicMock(), "offline", chat)


def test_300_worker_jobs_restart_publish_then_resume(tmp_path, pool):
    symbols = [BTC] + [f"S{i}/USDT:USDT" for i in range(299)]
    inventory = MagicMock()
    inventory.get_ranked_symbols.return_value = symbols
    runtime = MagicMock()
    runtime._opportunity_pool.return_value = pool
    path = tmp_path/"queue"
    checked_at = []

    def refresh_tracked(stop_event):
        assert not stop_event.is_set()
        checked_at.append(scan.queue.progress()["done"])
        assert pool.get_best_setups()[0].symbol == BTC

    def scanner():
        return ScanService(runtime, ScanQueue(path), inventory, analysis_gap_seconds=0, continuous=True,
                           refresh_tracked_setups=refresh_tracked)
    scan = scanner()
    scan.roll_cycle()
    gen = scan.queue.current_generation()
    retry = []
    def analyze(symbol):
        if symbol == symbols[1] and not retry:
            retry.append(symbol)
            return {"ok":False, "error":"temporary"}
        done = scan.queue.progress()["done"]
        if done < 10:
            assert not pool.get_best_setups()
        else:
            assert checked_at[-1] == done - done % 10
        if done == 298:
            scan._stop_event.set()
        row = observation(symbol, setup=symbol==BTC)
        return {"ok":True, "cycle_result":row}
    runtime.analyze_for_cycle.side_effect = analyze
    scan._worker_loop()
    assert scan.queue.progress()["done"] == 299 and retry
    assert checked_at == list(range(10, 300, 10))
    assert pool.get_best_setups()[0].symbol == BTC
    assert not pool.tracking.tracked("-10")
    scan.queue.close()
    scan = scanner()
    assert scan.queue.current_generation() == gen
    first = True
    def finish(symbol):
        nonlocal first
        if first:
            first = False
            return {"ok":True, "cycle_result":observation(symbol, setup=False)}
        scan._stop_event.set()
        return {"ok":False, "error":"temporary"}
    runtime.analyze_for_cycle.side_effect = finish
    scan._worker_loop()
    assert scan.queue.progress(gen)["done"] == 300
    assert checked_at == list(range(10, 301, 10))
    assert scan.queue.current_generation() == gen+1 and scan.queue.progress()["total"] == 300
    assert pool.get_best_setups()[0].symbol == BTC
    assert not pool.publish_cycle(gen, [])
    bot = service()
    assert "BTC" in bot.execute_command("/havuz")
    assert not pool.tracking.tracked(bot.chat_id)
    assert "BTC" in bot.execute_command("/eniyi5")
    assert "BTC" in bot.execute_command("/islemler")
    scan.queue.close()


def test_restart_checks_published_batch_before_claiming_next_symbol(tmp_path, pool):
    queue = ScanQueue(tmp_path/"queue")
    symbols = [BTC] + [f"S{i}/USDT:USDT" for i in range(299)]
    generation = queue.rebuild(symbols)["generation"]
    for _ in range(10):
        claim = queue.claim_next()
        symbol = claim["symbol"]
        queue.complete(symbol, True, claim=claim, result=observation(symbol, setup=symbol == BTC))

    runtime = MagicMock()
    runtime._opportunity_pool.return_value = pool

    def interrupt(stop_event):
        stop_event.set()

    scanner = ScanService(runtime, queue, MagicMock(), continuous=True, refresh_tracked_setups=interrupt)
    scanner.roll_cycle()
    marker = pool.tracking.get_meta("published_scan_batch")
    assert marker
    assert not pool.tracking.get_meta("checked_scan_batch")
    assert queue.progress()["done"] == 10

    calls = []
    scanner = ScanService(runtime, queue, MagicMock(), continuous=True, analysis_gap_seconds=0,
                          refresh_tracked_setups=lambda _: calls.append("check"))

    def analyze(symbol):
        calls.append(symbol)
        scanner._stop_event.set()
        return {"ok": True, "cycle_result": observation(symbol, setup=False)}

    runtime.analyze_for_cycle.side_effect = analyze
    scanner._worker_loop()
    assert calls == ["check", symbols[10]]
    assert pool.tracking.get_meta("checked_scan_batch") == marker
    assert queue.progress(generation)["done"] == 11
    queue.close()


def test_chat_lifecycle_cleanup_outbox_and_restart(pool):
    chat = service()
    other = service("13")
    pool.clean_published_if_due(100)
    first = observation()
    pool.publish_cycle(1,[first])
    chat.execute_command("/eniyi10")
    chat.execute_command("/eniyi5")
    assert len(pool.tracking.tracked(chat.chat_id)) == 1
    assert not pool.clean_published_if_due(DAY+99)
    assert pool.clean_published_if_due(DAY+100)
    assert "BTC" in chat.execute_command("/eniyi5")
    assert "GİRİŞ BEKLEYENLER" in chat.execute_command("/islemler")
    pool.publish_cycle(2,[observation(stamp=2,setup=False)])
    assert "GİRİŞ BEKLEYENLER" in chat.execute_command("/islemler")
    pool.publish_cycle(3,[observation(stamp=3,setup=False,broken=True)])
    assert "GİRİŞ BEKLEYENLER" not in chat.execute_command("/islemler")
    recovered = observation(stamp=4)
    pool.publish_cycle(4,[recovered])
    assert "GİRİŞ BEKLEYENLER" in chat.execute_command("/islemler")
    assert "BTC" not in other.execute_command("/islemler")
    chat._api = MagicMock(return_value={"message_id": 1, "chat":{"id":chat.chat_id}})
    chat._deliver_notifications()
    chat._deliver_notifications()
    assert chat._api.call_count == 2
    for call in chat._api.call_args_list:
        assert "Stop: 49500.0" in call.args[1]["text"]
        assert "TP1: 51000.0 | TP2: 52000.0 | TP3: 53000.0" in call.args[1]["text"]
    assert "TP3: 53000.0" in chat.execute_command("/islemler")
    assert "KALDIRILDI" in chat._api.call_args_list[0].args[1]["text"]
    assert "YENİ SETUP" in chat._api.call_args_list[1].args[1]["text"]
    again = OpportunityPool(base_path=pool.base_path, auto_persist=False)
    try:
        assert len(again.tracking.tracked(chat.chat_id)) == 2
        assert again.tracking.get_meta("pool_cleanup_ms") == str(DAY+100)
        assert not again.tracking.pending_notifications(chat.chat_id)
    finally:
        again.stop()


def test_manual_command_replaces_waiting_and_rejects_late_observation(pool):
    bot = service()
    row = observation(stamp=10)
    bot.runtime.normalize_symbol.return_value = BTC
    result = engine_shaped_result()
    result["strategy_lab"]["regime"] = {"label":"TREND"}
    result["strategy_lab"]["selected"].update(risk_validation={"eligible":True},
        risk_plan={"final_geometry_reconciled":True,"risk_setup_valid":True})
    bot.runtime.analyze_symbol.return_value = dict(ok=True, result=result,cycle_result=row)
    assert "LONG" in bot.execute_command("/btc")
    assert not pool.get_best_setups()
    assert len(pool.tracking.tracked(bot.chat_id)) == 1
    changed = observation(stamp=11)
    changed["setup"].update(setup_id="next",tp3=54000)
    pool.tracking.follow_analysis(bot.chat_id,changed)
    pool.publish_cycle(1,[row])
    records = pool.tracking.tracked(bot.chat_id)
    assert [r[2] for r in records] == ["WAITING","INVALIDATED"]
    assert records[0][3]["tp3"] == 54000


@pytest.mark.parametrize("finish",["targets","stop","ambiguous"])
def test_virtual_candles_and_midnight(pool, finish, monkeypatch):
    import datetime as dt
    import telegram_tracking
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Istanbul")
    now = dt.datetime(2026,11,18,20,0,tzinfo=zone)
    start = int(now.timestamp()*1000)
    monkeypatch.setattr(telegram_tracking.time,"time",lambda:start/1000)
    chat = service()
    pool.tracking.follow_analysis(chat.chat_id,observation())
    def bar(i, low, high):
        return SimpleNamespace(time=start+300000*i, low=low, high=high, open=(low+high)/2, close=(low+high)/2)
    def advance(i,low,high):
        monkeypatch.setattr(telegram_tracking.time,"time",lambda:(start+(i+1)*300000)/1000)
        pool.tracking.advance_tracking(BTC,[bar(i,low,high)])
        return pool.tracking.tracked(chat.chat_id)[0]
    assert advance(1,51000,52000)[2]=="WAITING"
    assert advance(2,49999,50050)[2]=="ACTIVE"
    pool.publish_cycle(1,[observation(stamp=3,setup=False,broken=True)])
    assert pool.tracking.tracked(chat.chat_id)[0][2]=="ACTIVE"
    if finish=="ambiguous":
        assert advance(3,49000,52000)[2]=="AMBIGUOUS"
    elif finish=="stop":
        assert advance(3,49400,49800)[3]["status"]=="SL"
    else:
        assert advance(3,50500,51100)[3]["tps_hit"]==[1]
        assert advance(4,51500,52100)[3]["tps_hit"]==[1,2]
        assert advance(5,52500,53100)[3]["status"]=="TP3"
    kinds=[m for _,m in pool.tracking.pending_notifications(chat.chat_id)]
    assert len(kinds)==len(set(kinds))
    class Tomorrow(dt.datetime):
        @classmethod
        def now(cls,tz=None):
            return now + dt.timedelta(days=1)
    monkeypatch.setattr(telegram,"datetime",Tomorrow)
    if finish!="ambiguous":
        assert "İŞLEMLERİM — 0" in chat.execute_command("/islemler")
        assert "BTC" in chat.execute_command("/gecmis")
    else:
        assert "belirsiz" in chat.execute_command("/islemler")


@pytest.mark.parametrize("cmd",TELEGRAM_COMMANDS,ids=lambda cmd:cmd.name)
def test_menu_group_dispatch_arguments_and_service_failure(cmd, monkeypatch):
    bot = service()
    bot._bot_username = "atlas"
    handler = MagicMock(return_value="sonuç")
    monkeypatch.setattr(bot,cmd.handler,handler)
    arg = "20" if cmd.parameter_name=="limit" else "BTC"
    raw = f"/{cmd.name}@atlas" + (f" {arg}" if cmd.takes_parameter else "")
    import time
    update = dict(message=dict(chat={"id":bot.chat_id},text=raw,date=int(time.time())))
    bot._handle_update(update)
    queued,_ = bot._command_queue.get_nowait()
    assert bot.execute_command(queued)=="sonuç"
    if cmd.takes_parameter:
        handler.assert_called_once_with(arg)
    invalid = f"/{cmd.name}" + ("" if cmd.takes_parameter else " extra")
    assert "KULLANIM" in bot.execute_command(invalid)
    handler.side_effect = RuntimeError("internal")
    assert bot.execute_command(raw)=="Komut tamamlanamadı. Biraz sonra tekrar deneyin."
    update["message"]["chat"]["id"]="other"
    bot._handle_update(update)
    assert bot._command_queue.empty()



def test_failed_telegram_delivery_keeps_chat_unsubscribed(pool):
    bot = service()
    pool.publish_cycle(1, [observation()])
    bot._api = MagicMock(side_effect=RuntimeError("transport"))
    bot._command_and_reply("/eniyi5")
    assert not pool.tracking.tracked(bot.chat_id)
    bot._api.side_effect = None
    bot._command_and_reply("/eniyi5")
    assert len(pool.tracking.tracked(bot.chat_id)) == 1


def test_concurrent_revisions_keep_newest_observation(pool):
    from concurrent.futures import ThreadPoolExecutor
    def request(stamp):
        row = observation(stamp=stamp)
        row["setup"]["setup_id"] = str(stamp)
        row["setup"]["tp3"] += stamp
        pool.tracking.follow_analysis("-1", row)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(request, [1, 10, 8, 5, 10, 7]))
    live = [plan for _,_,state,plan in pool.tracking.tracked("-1") if state=="WAITING"]
    assert len(live)==1 and live[0]["tp3"]==53010


def test_runtime_market_input_to_stage_and_manual_portfolio(pool, monkeypatch):
    import time
    import threading
    import atlas_runtime as module
    runtime = make_runtime()
    runtime._journal_lock = threading.Lock()
    runtime.engine = MagicMock()
    runtime.engine.analyze.return_value = engine_shaped_result()
    selected = runtime.engine.analyze.return_value["strategy_lab"]["selected"]
    runtime.engine.analyze.return_value["strategy_lab"]["regime"]={"label":"TREND"}
    selected.update(risk_validation={"eligible": True}, risk_plan={
        "final_geometry_reconciled": True, "risk_setup_valid": True})
    runtime._scanner_stats = {}
    runtime._latest_analysis_by_symbol = {}
    runtime._latest_analysis_at = {}
    for name in ("_inc","_log","_set_status","_accumulate_strategy_telemetry","_register_result",
                 "_prune_latest_analyses"):
        monkeypatch.setattr(runtime,name,MagicMock())
    monkeypatch.setattr(runtime,"_get_analysis_lock",lambda symbol:threading.Lock())
    monkeypatch.setattr(runtime,"symbol_exists",lambda symbol:True)
    for name in ("get_correlation_universe","get_smt_universe"):
        monkeypatch.setattr(module,name,lambda **kwargs:{})
    bar = SimpleNamespace(time=int(time.time()*1000)-901000,open=50000,low=49900,high=50100,close=50000,volume=10)
    monkeypatch.setattr(module,"get_market_data",lambda *args,**kwargs:{"symbol":BTC,"15m":[bar]})
    result = runtime.analyze_for_cycle(BTC)
    assert result["ok"], result.get("error")
    assert result["cycle_result"]["setup"] and not pool.get_best_setups()
    bot = telegram.TelegramCommandService(runtime,"offline","1")
    assert "LONG" in bot.execute_command("/btc")
    assert "GİRİŞ BEKLEYENLER" in bot.execute_command("/islemler")
    assert not pool.get_best_setups()
    pool.publish_cycle(1,[result["cycle_result"]])
    assert pool.get_best_setups()[0].setup_version==1
    assert bot.execute_command("/eniyi5").count("BTC")==1


def test_delivery_claim_has_one_owner_and_unknown_result_survives_restart(pool):
    from concurrent.futures import ThreadPoolExecutor
    bot = service()
    pool.publish_cycle(1,[observation()])
    bot.execute_command("/eniyi5")
    pool.publish_cycle(2,[observation(stamp=2,setup=False,broken=True)])
    with ThreadPoolExecutor(max_workers=4) as threads:
        claims = list(threads.map(lambda _: pool.tracking.claim_notification(bot.chat_id), range(4)))
    claim, = [item for item in claims if item]
    event_id, _, attempt = claim
    assert pool.tracking.claim_notification("13") is None
    # Simulate the process disappearing after the send intent was committed.
    with pool.tracking._transaction() as conn:
        conn.execute("UPDATE chat_event_delivery SET next_at=0 WHERE event_id=?", (event_id,))
    again = OpportunityPool(base_path=pool.base_path,auto_persist=False)
    try:
        assert not again.tracking.claim_notification(bot.chat_id)
        assert again.tracking.unconfirmed_notifications(bot.chat_id)==1
        again.tracking.finish_notification("13",event_id,attempt,"sent",message_id=123)
        assert again.tracking.unconfirmed_notifications(bot.chat_id)==1
    finally:
        again.stop()


@pytest.mark.parametrize("failure", ["retry","uncertain","wrong_chat"])
def test_delivery_requires_acknowledgement_and_only_retries_definite_failure(pool, failure, monkeypatch):
    import pool_store
    bot = service()
    pool.publish_cycle(1,[observation()])
    bot.execute_command("/eniyi5")
    pool.publish_cycle(2,[observation(stamp=2,setup=False,broken=True)])
    now = [1000]
    monkeypatch.setattr(pool_store.time,"time",lambda:now[0])
    bad = telegram.TelegramDeliveryError(failure, retry_after=30) if failure!="wrong_chat" else {
        "chat":{"id":999},"message_id":321}
    bot._api = MagicMock(side_effect=[bad,{"chat":{"id":bot.chat_id},"message_id":234}])
    bot._deliver_notifications()
    bot._deliver_notifications()
    assert bot._api.call_count==1
    now[0]+=31
    bot._deliver_notifications()
    if failure=="retry":
        assert bot._api.call_count==2
        assert not pool.tracking.pending_notifications(bot.chat_id)
    else:
        assert bot._api.call_count==1
        assert pool.tracking.unconfirmed_notifications(bot.chat_id)==1


def test_replacement_during_external_reply_preserves_membership(pool):
    bot = service()
    pool.publish_cycle(1,[observation()])
    def send(*args,**kwargs):
        updated = observation(stamp=2)
        updated["setup"].update(setup_id="replacement",tp3=54000)
        pool.publish_cycle(2,[updated])
        return {"message_id":5,"chat":{"id":bot.chat_id}}
    bot._api = send
    bot._command_and_reply("/eniyi5")
    plans = pool.tracking.tracked(bot.chat_id)
    assert [(p[2],p[3]["tp3"]) for p in plans]==[("WAITING",54000),("INVALIDATED",53000)]


def test_replayed_market_snapshot_cannot_rewind_partial_pnl(pool, monkeypatch):
    import time
    start = int(time.time() // 900) * 900_000
    monkeypatch.setattr(time, "time", lambda: start / 1000)
    from types import SimpleNamespace
    bot = service()
    row = observation()
    row["setup"]["execution_costs"]={"partial_exit_weights":{"tp1":0.2,"tp2":0.3,"tp3":0.5}}
    pool.tracking.follow_analysis(bot.chat_id,row)
    start = pool.tracking.tracked(bot.chat_id)[0][3]["opened_at"]
    def bar(i, low, high, close):
        return SimpleNamespace(time=start+300000*i,low=low,high=high,close=close,open=close)
    fill, partial = bar(1,49950,50050,50000), bar(2,50600,51050,50900)
    monkeypatch.setattr(time, "time", lambda: start / 1000 + 2700)
    pool.tracking.advance_tracking(BTC,[fill,partial])
    pool.tracking.advance_tracking(BTC,[fill])
    outcome=pool.tracking.tracked(bot.chat_id)[0][3]
    assert outcome["tps_hit"]==[1]
    assert outcome["realized_r"]==pytest.approx(.4)
    assert outcome["open_r"]==pytest.approx(.8*900/500)
    assert outcome["mark_time"]==partial.time+300000


def test_published_rr_requires_finite_cost_adjusted_reward():
    runtime=make_runtime()
    selected=engine_shaped_result()["strategy_lab"]["selected"]
    selected.pop("estimated_net_rr")
    assert runtime._setup_to_candidate(selected,BTC) is None
    selected["risk_plan"]={"weighted_net_rr":1.25}
    selected["estimated_net_rr"]=2.5
    assert runtime._setup_to_candidate(selected,BTC).net_rr_after_costs==1.25


def test_pr219_jobs_without_staged_evidence_are_repaired_before_publication(tmp_path,pool):
    queue=ScanQueue(tmp_path/"old")
    symbols=[BTC]+[f"T{i}/USDT:USDT" for i in range(299)]
    generation=queue.rebuild(symbols)["generation"]
    while (claim:=queue.claim_next()):
        symbol=claim["symbol"]
        row=observation(symbol,setup=False) if symbol!=BTC else None
        queue.complete(symbol,True,claim=claim,result=row)
    runtime=MagicMock()
    runtime._opportunity_pool.return_value=pool
    scanner=ScanService(runtime,queue,MagicMock(),continuous=True)
    scanner.roll_cycle()
    assert queue.current_generation()==generation and queue.progress()["done"]==299
    assert not pool.tracking.get_meta("published_generation")
    claim=queue.claim_next()
    assert claim["symbol"]==BTC
    queue.complete(BTC,True,claim=claim,result=observation())
    scanner.roll_cycle()
    assert pool.get_best_setups()[0].symbol==BTC
    scanner.roll_cycle()
    assert queue.progress()["pending"]==0
    queue.close()


def test_smc_without_h4_and_invalid_generators_are_not_structural_invalidation(monkeypatch):
    import strategy_lab
    report=strategy_lab.SevenStrategyLab().analyze({"symbol":BTC})
    smc=next(row for row in report["strategies"] if row["strategy_id"]=="smc")
    assert smc["status"]=="MISSING_DATA"
    monkeypatch.setattr(strategy_lab,"_setup_diagnostic",lambda *args,**kwargs:"INVALID_DATA: ATR unavailable")
    report=strategy_lab.SevenStrategyLab().analyze({"symbol":BTC})
    assert {row["status"] for row in report["strategies"]}=={"INVALID_DATA"}


@pytest.mark.parametrize("command", ["/kaldir arb", "/kaldır@atlas arb", "/çıkart@atlas arb"])
def test_remove_and_resume_symbol_persists_and_is_chat_scoped(tmp_path, monkeypatch, command):
    import time
    from telegram_command_service import is_recognized_command

    path = tmp_path / "manual"
    pool = OpportunityPool(base_path=path, auto_persist=False)
    bot = service()
    other = service("other")
    arb = "ARB/USDT:USDT"
    now = int(time.time() * 1000)
    try:
        seen = observation(arb, stamp=now-5000)
        monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
        for chat in (bot, other):
            pool.tracking.follow_analysis(chat.chat_id, seen)
        pool.tracking.follow_analysis(bot.chat_id, observation())
        assert is_recognized_command(command)
        assert "çıkarıldı" in bot.execute_command(command)
        assert "listesinde yok" in bot.execute_command("/cikart ARB/USDT")
        assert "ARB" not in bot.execute_command("/işlemler")
        assert "BTC" in bot.execute_command("/işlemler")
        assert "ARB" in other.handle_islemler()
        assert "Kullanıcı takipten çıkardı" in bot.handle_history()
        pool.stop()
        pool = OpportunityPool(base_path=path, auto_persist=False)
        monkeypatch.setattr(opportunity_pool, "_pool_instance", pool)
        newer = observation(arb, stamp=now+2000)
        pool.tracking.follow_delivered(bot.chat_id, [newer])
        assert "ARB" not in bot.handle_islemler()
        assert "takip açıldı" in bot.execute_command("/ekle ARB")
        pool.tracking.follow_delivered(bot.chat_id, [seen])
        assert "ARB" not in bot.handle_islemler()
        pool.tracking.follow_analysis(bot.chat_id, observation(arb, stamp=int(time.time()*1000)+1))
        assert "ARB" in bot.handle_islemler()
        assert len([row for row in pool.tracking.tracked(bot.chat_id) if row[0]==arb]) == 2
    finally:
        pool.stop()


def test_delivered_top_ten_tracks_current_setups_after_explicit_reenable(pool, monkeypatch):
    import time

    bot = service()
    now = [1_800_000_000]
    monkeypatch.setattr(time, "time", lambda: now[0])
    tut, ub, morpho = ("TUT/USDT:USDT", "UB/USDT:USDT", "MORPHO/USDT:USDT")
    observations = [observation(symbol, stamp=now[0]*1000) for symbol in (tut, ub, morpho)]
    pool.publish_cycle(1, observations)

    now[0] += 1
    for symbol in (tut, ub, morpho):
        pool.tracking.set_symbol_tracking(bot.chat_id, symbol, enabled=True)
    pool.tracking.set_symbol_tracking(bot.chat_id, ub, enabled=False)

    def send(method, payload, **kwargs):
        for symbol in ("TUT/USDT", "UB/USDT", "MORPHO/USDT"):
            assert symbol in payload["text"]
        now[0] += 900
        # A newer neutral analysis should not prevent tracking the setup still in the pool.
        pool.publish_cycle(2, [observation(tut, stamp=now[0]*1000, setup=False)])
        pool.tracking.set_symbol_tracking(bot.chat_id, morpho, enabled=False)
        return {"message_id": 17, "chat": {"id": bot.chat_id}}

    bot._api = MagicMock(side_effect=send)
    bot._command_and_reply("/eniyi10")
    assert [(row[0], row[2]) for row in pool.tracking.tracked(bot.chat_id)] == [(tut, "WAITING")]
    assert "TUT/USDT" in bot.execute_command("/islemler")


def test_no_new_trigger_preserves_setup_until_evidence_breaks_its_stop(tmp_path, monkeypatch):
    import time
    clock = [1_800_000_000]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    path = tmp_path / "pool"
    pool = OpportunityPool(base_path=path, auto_persist=False)
    row = observation(stamp=clock[0]*1000)
    try:
        pool.publish_cycle(1, [row])
        pool.follow_best("chat", 1)
        clock[0] += 900
        neutral = dict(observation(stamp=clock[0]*1000, setup=False, broken=True), structure_close=51000)
        pool.publish_cycle(2, [neutral])
        assert pool.get_best_setups()[0].setup_id == row["setup"]["setup_id"]
        assert pool.tracking.tracked("chat")[0][2] == "WAITING"
        pool.publish_cycle(3, [dict(row, cutoff=neutral["cutoff"], observed=neutral["observed"])])
        assert pool.tracking.validation_counts() == {row["setup"]["strategy_id"]:1}
        clock[0] += 3 * 3600
        assert not pool.get_best_setups() and pool.get_stats()["validated_stored"] == 1
        pool.stop()
        pool = OpportunityPool(base_path=path, auto_persist=False)
        assert pool.get_stats()["validated_stored"] == 1 and not pool.get_best_setups()
        breach = dict(neutral, cutoff=clock[0]*1000, observed=clock[0]*1000, structure_close=49499)
        pool.publish_cycle(4, [breach])
        assert pool.get_stats()["validated_stored"] == 0
        assert pool.tracking.tracked("chat")[0][2] == "INVALIDATED"
    finally:
        pool.stop()


def test_priority_tracking_checks_waiting_structure_outside_scan_queue(pool, monkeypatch):
    import threading
    import time

    runtime = make_runtime()
    runtime._waiting_structure_checked = {}
    runtime._opportunity_pool = lambda: pool
    runtime.logger = MagicMock()
    clock = [1800000000]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    history = MagicMock()
    monkeypatch.setattr("tracking_history.TrackingHistory", lambda: history)
    advance = MagicMock()
    monkeypatch.setattr(pool.tracking, "advance_tracking", advance)
    row = observation(BTC, stamp=clock[0] * 1000)
    pool.publish_cycle(1, [row])
    pool.follow_best("chat", 1)

    clock[0] += 1800
    cutoff = (clock[0] // 900 - 1) * 900000
    replacement = observation(BTC, stamp=clock[0]*1000, broken=True)
    replacement["setup"]["setup_id"] = "fresh-opportunity"
    evidence = dict(replacement, cutoff=cutoff, structure_close=51000)
    runtime.analyze_for_cycle = MagicMock(return_value={"ok": True, "cycle_result": evidence})
    stop_event = threading.Event()
    runtime._refresh_tracked_setups(stop_event)
    advance.assert_called_once_with(BTC, history=history, stop_event=stop_event)
    runtime.analyze_for_cycle.assert_called_once_with(BTC)
    assert pool.tracking.tracked("chat")[0][2] == "WAITING"
    runtime._refresh_tracked_setups(stop_event)
    runtime.analyze_for_cycle.assert_called_once_with(BTC)

    clock[0] += 900
    evidence.update(cutoff=cutoff + 900000, observed=clock[0]*1000, structure_close=49499)
    runtime._refresh_tracked_setups(stop_event)
    assert not pool.get_best_setups()
    assert [(row[1], row[2]) for row in pool.tracking.tracked("chat")] == [(1, "INVALIDATED")]
    assert "SETUP KALDIRILDI" in pool.tracking.pending_notifications("chat")[-1][1]


def test_unranked_or_rejected_plan_needs_fresh_selection_to_be_displayed(pool):
    row = observation()
    pool.publish_cycle(1, [row], [BTC])
    pool.publish_cycle(2, [], ["OTHER"])
    assert not pool.get_best_setups() and pool.get_stats()["validated_stored"] == 1
    pool.publish_cycle(3, [], [BTC])
    assert not pool.get_best_setups()
    pool.publish_cycle(4, [dict(row, observed=4)], [BTC])
    assert pool.get_best_setups()
    rejected = dict(row, observed=5, setup=None, blocked_strategies=[row["setup"]["strategy_id"]])
    pool.publish_cycle(5, [rejected], [BTC])
    assert not pool.get_best_setups() and pool.get_stats()["validated_stored"] == 1
