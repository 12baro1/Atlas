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
    def scanner():
        return ScanService(runtime, ScanQueue(path), inventory, analysis_gap_seconds=0, continuous=True)
    scan = scanner()
    scan.roll_cycle()
    gen = scan.queue.current_generation()
    retry = []
    def analyze(symbol):
        if symbol == symbols[1] and not retry:
            retry.append(symbol)
            return {"ok":False, "error":"temporary"}
        if scan.queue.progress()["done"] == 298:
            scan._stop_event.set()
        row = observation(symbol, setup=symbol==BTC)
        return {"ok":True, "cycle_result":row}
    runtime.analyze_for_cycle.side_effect = analyze
    scan._worker_loop()
    assert scan.queue.progress()["done"] == 299 and retry
    assert not pool.get_best_setups() and not pool.tracking.tracked("-10")
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
    assert scan.queue.current_generation() == gen+1 and scan.queue.progress()["total"] == 300
    assert pool.get_best_setups()[0].symbol == BTC
    assert not pool.publish_cycle(gen, [])
    bot = service()
    assert "BTC" in bot.execute_command("/havuz")
    assert not pool.tracking.tracked(bot.chat_id)
    assert "BTC" in bot.execute_command("/eniyi5")
    assert "BTC" in bot.execute_command("/islemler")
    scan.queue.close()


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
    assert "havuzu boş" in chat.execute_command("/eniyi5")
    assert "Giriş bekliyor" in chat.execute_command("/islemler")
    pool.publish_cycle(2,[observation(stamp=2,setup=False)])
    assert "Giriş bekliyor" in chat.execute_command("/islemler")
    pool.publish_cycle(3,[observation(stamp=3,setup=False,broken=True)])
    assert "Giriş bekliyor" not in chat.execute_command("/islemler")
    recovered = observation(stamp=4)
    pool.publish_cycle(4,[recovered])
    assert "Giriş bekliyor" in chat.execute_command("/islemler")
    assert "BTC" not in other.execute_command("/islemler")
    chat._api = MagicMock()
    chat._deliver_notifications()
    chat._deliver_notifications()
    assert chat._api.call_count == 2
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
        return SimpleNamespace(time=start+900000*i, low=low, high=high, open=(low+high)/2, close=(low+high)/2)
    def advance(i,low,high):
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
    assert "Giriş bekliyor" in bot.execute_command("/islemler")
    assert not pool.get_best_setups()
    pool.publish_cycle(1,[result["cycle_result"]])
    assert pool.get_best_setups()[0].setup_version==1
    assert bot.execute_command("/eniyi5").count("BTC")==1
