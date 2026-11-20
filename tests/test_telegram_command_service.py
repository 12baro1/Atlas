import time

from telegram_command_service import (
    TelegramCommandService,
    is_recognized_command,
    normalize_command,
    split_message,
    format_daily_signal_report,
    _format_telegram_card,
)


def test_normalize_plain_and_addressed_commands():
    assert normalize_command("  BTC   ") == "BTC"
    assert normalize_command("/help@Oakmontincbot") == "help"


def test_reply_http_failure_keeps_token_and_private_text_out_of_logs(monkeypatch, caplog):
    import requests
    service = TelegramCommandService(None, "private-test-token", "123")
    def fail(url, **kwargs):
        raise requests.ConnectionError(f"could not send {kwargs['json']['text']} to {url}")
    monkeypatch.setattr(service._reply_session, "post", fail)
    service._send_command_reply("private-test-message")
    assert "sendMessage failed" in caplog.text
    assert "private-test-token" not in caplog.text
    assert "private-test-message" not in caplog.text


def test_recognizes_terminal_commands():
    for command in (
        "/BTC",
        "/ETH",
        "/tara",
        "/tara 20",
        "/setup BTC",
        "/havuz",
        "/gecmis",
        "/motorlar",
        "/veri",
        "/BTC@Oakmontincbot",
        "en iyi 5 işlem",
        "20 tara",
        "30 tara",
        "20 coin tara",
        "50 analiz et",
        "tüm piyasayı tara",
        "likidite BTC",
        "performans",
        "öğrenme",
        "yardım",
    ):
        assert is_recognized_command(command), command


def test_ignores_unrecognized_group_chat():
    assert not is_recognized_command("Günaydın herkes")
    assert not is_recognized_command("fiyat kaç olur?")
    assert not is_recognized_command("BTC")
    assert not is_recognized_command("ETH")
    assert not is_recognized_command("btc analiz eder misin")


def test_split_message_respects_telegram_limit():
    chunks = split_message(("satır\n" * 1200), limit=100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_service_requires_explicit_group_target():
    service = TelegramCommandService(object(), "token", "-100123")
    assert service.enabled
    service_without_chat = TelegramCommandService(object(), "token", "")
    assert not service_without_chat.enabled



def test_mevcut_daily_report_uses_turkey_local_day_and_net_r():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 11, 16, 1, 0, tzinfo=tz)
    stamp = int(datetime(2026, 11, 16, 0, 10, tzinfo=tz).timestamp() * 1000)
    previous_day = int(datetime(2026, 11, 15, 23, 50, tzinfo=tz).timestamp() * 1000)
    rows = [
        {"signal_id": "A1", "symbol": "BTC/USDT", "direction": "LONG", "opened_at": stamp,
         "status": "PENDING", "entry_reached": True, "realized_r": 0.0},
        {"signal_id": "A2", "symbol": "ETH/USDT", "direction": "SHORT", "opened_at": stamp,
         "status": "TP1", "entry_reached": True, "realized_r": 0.5},
        {"signal_id": "A3", "symbol": "SOL/USDT", "direction": "LONG", "opened_at": stamp,
         "status": "SL", "entry_reached": True, "realized_r": -1.0},
        {"signal_id": "A4", "symbol": "XRP/USDT", "direction": "SHORT", "opened_at": stamp,
         "status": "EXPIRED", "entry_reached": False, "realized_r": 0.0},
        {"signal_id": "A5", "symbol": "ADA/USDT", "direction": "LONG", "opened_at": stamp,
         "status": "PENDING", "entry_reached": True, "entry_tracking_source": "market_reference",
         "realized_r": 0.0},
        {"signal_id": "OLD", "symbol": "OLD/USDT", "direction": "LONG", "opened_at": previous_day,
         "status": "TP3", "entry_reached": True, "realized_r": 2.0},
    ]

    report = format_daily_signal_report(rows, now=now)
    assert "Bugünkü setup + önceki günlerden açık: 5" in report
    assert "Giriş seviyesi mumda görüldü: 3" in report
    assert "MARKET referansı (fill teyitsiz): 1" in report
    assert "Giriş olmadı (süresi doldu): 1" in report
    assert "Net: -0.50R" in report
    assert "OLD/USDT" not in report
    assert "XRP/USDT" in report
    assert "Giriş seviyesi görülmedi" in report


def test_telegram_card_is_compact_and_keeps_trade_levels():
    card = {
        "symbol": "BTC/USDT:USDT", "direction": "LONG",
        "decision_action": "EXECUTE", "entry_type": "LIMIT",
        "entry": 100.0, "stop_loss": 99.0,
        "tp_levels": [101.0, 102.0, 103.0],
        "net_rr": 1.25, "strategy": "SMC",
        "setup_thesis": "Uzun teknik açıklama",
        "supporting_evidence": ["çok fazla kanıt"],
    }
    text = _format_telegram_card(card)
    assert "BTC/USDT — LONG" in text
    assert "Strateji: SMC" in text
    assert "Giriş (LIMIT): 100" in text
    assert "SL: 99" in text
    assert "TP3: 103" in text
    assert "Net RR: +1.25R" in text
    assert "Risk/Getiri" not in text
    assert "SETUP GEREKÇESİ" not in text
    assert "Uzun teknik açıklama" not in text
    assert "LIMIT giriş bekleniyor" in text


def test_recognizes_mevcut_command():
    assert is_recognized_command("/mevcut@Oakmontincbot")


def test_recognizes_cached_best_five_command():
    assert is_recognized_command("/eniyi5")
    assert is_recognized_command("/eniyi5@Oakmontincbot")



def test_telegram_service_queues_fresh_commands_without_blocking_poll(monkeypatch):
    service = TelegramCommandService(object(), "token", "-100123")
    called = []
    api_calls = []
    monkeypatch.setattr("telegram_command_service.is_recognized_command", lambda command: True)
    monkeypatch.setattr(service, "execute_command", lambda command: called.append(command) or "ok")
    monkeypatch.setattr(service, "_api", lambda *args, **kwargs: api_calls.append((args, kwargs)))

    service._handle_update({
        "update_id": 11,
        "message": {
            "date": int(time.time()),
            "text": "/BTC",
            "chat": {"id": -100123},
            "from": {"is_bot": False},
        },
    })

    queued_command, label = service._command_queue.get_nowait()
    service._command_queue.task_done()
    assert queued_command == "/BTC"
    assert label == "BTC"
    assert called == []
    assert api_calls == []  # only the final command result is sent


def test_telegram_service_ignores_queued_stale_analysis_commands(monkeypatch):
    service = TelegramCommandService(object(), "token", "-100123")
    called = []
    monkeypatch.setattr(service, "execute_command", lambda command: called.append(command) or "ok")
    monkeypatch.setattr(service, "_api", lambda *args, **kwargs: None)

    service._handle_update({
        "update_id": 10,
        "message": {
            "date": int(time.time()) - 1200,
            "text": "/BTC",
            "chat": {"id": -100123},
            "from": {"is_bot": False},
        },
    })

    assert called == []


def test_runtime_signal_tracking_is_opt_in_by_default():
    import inspect
    from atlas_runtime import AtlasRuntime

    parameter = inspect.signature(AtlasRuntime.analyze_symbol).parameters["track_signal"]
    assert parameter.default is False



def test_telegram_card_omits_verbose_evidence_details():
    card = {
        "symbol": "ETH/USDT:USDT", "direction": "SHORT",
        "decision_action": "EXECUTE_WITH_CAUTION", "entry_type": "MARKET",
        "entry": 3420.0, "stop_loss": 3455.0,
        "tp_levels": [3385.0, 3350.0, 3310.0],
        "net_rr": 2.1, "strategy_id": "orderflow_momentum",
        "setup_thesis": "Satıcı baskısı devam ediyor",
        "supporting_evidence": ["CVD negatif", "Agresif satış işlemleri"],
        "opposing_evidence": ["Yakın destek bölgesi"],
    }
    message = _format_telegram_card(card)
    assert "Strateji: ORDERFLOW MOMENTUM" in message
    assert "Net RR: +2.10R" in message
    assert "CVD negatif" not in message
    assert "DİKKAT" not in message
    assert "Karşı kanıt" not in message
    assert "borsaya emir gönderilmedi" in message


def test_mevcut_report_shows_levels_strategy_and_tp_progress():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 11, 16, 12, 0, tzinfo=tz)
    stamp = int(now.timestamp() * 1000)
    rows = [{
        "signal_id": "ATL-20261116-000001",
        "symbol": "BTC/USDT:USDT",
        "direction": "LONG",
        "opened_at": stamp,
        "status": "PENDING",
        "entry_reached": True,
        "entry_tracking_source": "closed_ohlc",
        "entry": 96250.0,
        "stop_loss": 95700.0,
        "tp1": 96800.0,
        "tp2": 97350.0,
        "tp3": 98000.0,
        "tps_hit": [1],
        "realized_r": 0.5,
        "payload": {"strategy": "SMC"},
    }]
    report = format_daily_signal_report(rows, now=now)
    assert "AKTİF İŞLEMLER (1)" in report
    assert "Strateji: SMC" in report
    assert "Giriş: 96,250" in report
    assert "Stop Loss: 95,700" in report
    assert "TP1: 96,800" in report
    assert "TP1 ALINDI  |  TP2/TP3 TAKİPTE" in report
    assert "Gerçekleşen kısmi getiri (brüt): +0.50R" in report
    assert "Net: +0.00R" in report


def test_price_formatter_preserves_small_coin_precision():
    from telegram_command_service import _format_price
    assert _format_price(0.00001234) == "0.00001234"


def test_daily_report_keeps_previous_day_open_setups_visible():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 11, 18, 12, 0, tzinfo=tz)
    opened = int(datetime(2026, 11, 17, 21, 0, tzinfo=tz).timestamp() * 1000)
    report = format_daily_signal_report([{
        "signal_id": "OLD-OPEN",
        "symbol": "BTC/USDT:USDT",
        "direction": "LONG",
        "opened_at": opened,
        "status": "PENDING",
        "entry_reached": True,
        "entry": 100.0,
        "stop_loss": 98.0,
        "tp1": 102.0,
        "tp2": 104.0,
        "tp3": 106.0,
        "tps_hit": [1],
        "trailing_stop": 100.0,
        "realized_r": 0.5,
    }], now=now)
    assert "BTC/USDT" in report
    assert "TP1 ALINDI" in report
    assert "Koruma stopu: 100" in report


def test_takip_shows_tp_progress_and_recent_stop_result():
    class Runtime:
        def signal_outcomes(self, **kwargs):
            return [
                {
                    "signal_id": "OPEN-1", "symbol": "BTC/USDT:USDT",
                    "direction": "LONG", "status": "PENDING",
                    "opened_at": 1_800_000_000_000, "entry": 100.0,
                    "stop_loss": 98.0, "tp1": 102.0, "tp2": 104.0,
                    "tp3": 106.0, "tps_hit": [1], "trailing_stop": 100.0,
                    "realized_r": 0.5, "payload": {"strategy": "SMC"},
                },
                {
                    "signal_id": "CLOSED-1", "symbol": "ETH/USDT:USDT",
                    "direction": "SHORT", "status": "SL",
                    "opened_at": 1_799_000_000_000, "resolved_at": 1_799_100_000_000,
                    "entry": 200.0, "stop_loss": 202.0, "tp1": 198.0,
                    "tp2": 196.0, "tp3": 194.0, "tps_hit": [1],
                    "trailing_stop": 200.0, "realized_r": 0.3,
                    "payload": {"strategy": "Order Flow"},
                },
            ]

    service = TelegramCommandService(Runtime(), "token", "chat")
    message = service.handle_takip()
    assert "Açık: 1 | Son kapanan: 1" in message
    assert "TP1 ALINDI" in message
    assert "Koruma stopu: 100" in message
    assert "Sonuç: SL" in message
    assert "Net sonuç: +0.30R" in message


def test_setuplar_reads_validated_pool_not_recent_analyses(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    candidate = SimpleNamespace(
        symbol="BTC/USDT:USDT", direction="LONG", strategy_name="SMC",
        entry_price=100.0, stop_loss=98.0, tp1=102.0, tp2=104.0,
        tp3=106.0, net_rr_after_costs=2.1, status="VALIDATED",
    )
    pool = SimpleNamespace(
        get_best_setups=lambda **kwargs: [candidate],
        get_active_setups=lambda: [],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)
    service = TelegramCommandService(SimpleNamespace(), "token", "chat")
    message = service.handle_setuplar()
    assert "BTC/USDT | LONG" in message
    assert "TP1: 102" in message
    assert "Durum: VALIDATED" in message


def test_mevcut_shows_signal_outcomes_without_mixing_pool_setups(monkeypatch):
    import telegram_command_service as telegram_module

    class Runtime:
        def signal_outcomes(self, **kwargs):
            return []

    def unexpected_pool_access():
        raise AssertionError("/mevcut must not read the opportunity pool")

    monkeypatch.setattr(telegram_module, "get_opportunity_pool", unexpected_pool_access)
    service = TelegramCommandService(Runtime(), "token", "chat")
    message = service.handle_mevcut()
    assert "ATLAS | BUGÜNÜN İŞLEM TAKİBİ" in message
    assert "Doğrulanmış havuz setup'ları" not in message


def test_takip_does_not_mix_untracked_pool_setups(monkeypatch):
    import telegram_command_service as telegram_module

    class Runtime:
        def signal_outcomes(self, **kwargs):
            return []

    def unexpected_pool_access():
        raise AssertionError("/takip must only read journal-tracked signals")

    monkeypatch.setattr(telegram_module, "get_opportunity_pool", unexpected_pool_access)
    message = TelegramCommandService(Runtime(), "token", "chat").handle_takip()
    assert "ATLAS | SİNYAL TAKİBİ" in message
    assert "Açık veya sonuçlanmış sinyal kaydı yok" in message
    assert "/islemler" in message

def test_setuplar_keeps_distinct_validated_setup_for_same_symbol_and_direction(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    candidate = SimpleNamespace(
        symbol="BTC/USDT:USDT", direction="LONG", strategy_name="SMC",
        entry_price=105.0, stop_loss=103.0, tp1=107.0, tp2=109.0,
        tp3=111.0, net_rr_after_costs=2.0, status="VALIDATED",
    )
    pool = SimpleNamespace(
        get_best_setups=lambda **kwargs: [candidate],
        get_active_setups=lambda: [],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)
    service = TelegramCommandService(SimpleNamespace(), "token", "chat")
    message = service.handle_setuplar()
    assert "BTC/USDT | LONG" in message
    assert "Giriş: 105" in message
    assert "TP3: 111" in message


def test_telegram_card_requires_three_ordered_targets():
    card = {
        "symbol": "BTC/USDT", "direction": "LONG",
        "decision_action": "EXECUTE", "entry_type": "MARKET",
        "entry": 100.0, "stop_loss": 99.0,
        "tp_levels": [101.0, 102.0],
        "net_rr": 2.0, "strategy": "SMC",
    }
    message = _format_telegram_card(card)
    assert "GEÇERLİ İŞLEM PLANI YOK" in message
    assert "TP1:" not in message
    assert "Giriş (MARKET)" not in message


def test_best_setups_output_includes_levels_per_displayed_plan(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    setup = SimpleNamespace(
        symbol="BTC/USDT:USDT", direction="LONG", strategy_name="SMC",
        setup_type="LIMIT", entry_price=100.0, stop_loss=98.0,
        tp1=102.0, tp2=104.0, tp3=106.0,
        rr_tp1=1.0, rr_tp2=2.0, rr_tp3=3.0,
        net_rr_after_costs=1.8, status="VALIDATED",
        created_at_ms=0, updated_at_ms=0,
    )
    pool = SimpleNamespace(follow_best=lambda chat, count: [setup])
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)
    service = TelegramCommandService(object(), "token", "chat")
    message = service._format_best_setups(5)
    assert message.splitlines() == ["EN İYİ 5 SETUP", "1. BTC/USDT | LONG | SMC | +1.80R",
                                    "Giriş: 100.0 | Stop: 98.0", "TP1: 102.0 | TP2: 104.0 | TP3: 106.0"]


def test_scan_status_contains_only_queue_and_market_status():
    class Runtime:
        def scan_status(self):
            return {
                "total": 300, "done": 77, "running": 1, "pending": 222,
                "failed": 0, "percent": 25.7, "workers_running": True,
                "inventory": {"symbol_count": 544, "ranking_source": "gateio_24h_quote_volume"},
                "strategy_telemetry": {"per_strategy": {"smc": {"setups": 99}}},
            }

    message = TelegramCommandService(Runtime(), "token", "chat").handle_scan_status()
    assert "77/300" in message
    assert "Gate.io" in message
    assert "24 saatlik USDT işlem hacmi" in message
    assert "SMC" not in message
    assert "/havuzdurum" in message


def test_pool_status_shows_only_persistent_pool_contents(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    pool = SimpleNamespace(
        get_stats=lambda: {"candidates": 3, "validated": 2, "active": 1, "history": 4},
        get_best_setups=lambda **kwargs: [],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)
    message = TelegramCommandService(SimpleNamespace(), "token", "chat").handle_pool_status()
    assert "ATLAS | FIRSAT HAVUZU" in message
    assert "Aday: 3" in message
    assert "Doğrulanmış: 2" in message
    assert "SMC" not in message
    assert "/islemler" in message


def test_statistics_shows_seven_strategy_funnel():
    class Runtime:
        def scan_status(self):
            return {
                "strategy_telemetry": {
                    "analyses": 10,
                    "raw_setups_generated": 7,
                    "common_filter_passed": 3,
                    "common_filter_rejected": 4,
                    "per_strategy": {"smc": {"setups": 2, "passed": 1, "rejected": 1}},
                }
            }

    message = TelegramCommandService(Runtime(), "token", "chat").handle_statistics()
    for name in (
        "SMC", "RELATIVE STRENGTH", "TREND PULLBACK",
        "ORDERFLOW MOMENTUM", "MEAN REVERSION",
        "LIQUIDATION CASCADE", "VOLATILITY BREAKOUT",
    ):
        assert name in message
    assert "ORTAK FİLTRE" in message

def test_performance_report_shows_cumulative_profit_loss_in_r():
    class Runtime:
        def signal_performance(self):
            return {
                "closed": 12, "wins": 7, "losses": 5, "winrate": 58.3,
                "positive_r": 8.25, "negative_r": -4.5, "net_r": 3.75,
                "profit_factor": 1.83, "tp1": 8, "tp2": 3, "tp3": 1, "sl": 5,
            }

        def manual_performance(self):
            return {
                "total": 4, "wins": 2, "losses": 2, "open": 1, "winrate": 50.0,
                "positive_r": 3.0, "negative_r": -2.0, "net_r": 1.0,
                "profit_factor": 1.5, "performance_basis": "mixed",
            }

    message = TelegramCommandService(Runtime(), "token", "chat").handle_performance()
    assert "Toplam kazanç: +8.25R" in message
    assert "Toplam kayıp: -4.50R" in message
    assert "Net sonuç: +3.75R" in message
    assert "Toplam kazanç: +3.00R" in message
    assert "Net sonuç: +1.00R" in message
    assert "TL/USDT tutarı değildir" in message

def test_unfollowed_removed_setups_are_private(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    removed_setup = {
        "symbol": "AVAX/USDT:USDT",
        "direction": "LONG",
        "strategy_name": "smc",
        "status": "INVALIDATED",
        "invalidation_reason": "STRATEGY_STRUCTURE_BROKEN",
        "closed_at_ms": 3000,
    }
    pool = SimpleNamespace(
        tracking=SimpleNamespace(tracked=lambda chat: []),
        get_best_setups=lambda **kwargs: [],
        get_active_setups=lambda: [],
        get_recent_history=lambda **kwargs: [removed_setup],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)

    class Runtime:
        def signal_outcomes(self, **kwargs):
            return []

    message = TelegramCommandService(Runtime(), "token", "chat").handle_islemler()
    assert "İŞLEMLERİM — 0" in message
    assert all(symbol not in message for symbol in ("BTC", "ETH", "SOL", "AVAX"))


def test_global_open_waiting_and_closed_do_not_subscribe_chat(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    pool = SimpleNamespace(
        tracking=SimpleNamespace(tracked=lambda chat: []),
        get_best_setups=lambda **kwargs: [],
        get_active_setups=lambda: [],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)

    class Runtime:
        def signal_outcomes(self, **kwargs):
            return [
                {
                    "signal_id": "A1", "symbol": "BTC/USDT:USDT", "direction": "LONG",
                    "status": "PENDING", "entry_reached": True, "opened_at": 3000,
                    "entry": 100, "stop_loss": 99, "tp1": 102, "tp2": 103, "tp3": 104,
                    "payload": {"strategy": "smc"},
                },
                {
                    "signal_id": "A2", "symbol": "ETH/USDT:USDT", "direction": "SHORT",
                    "status": "PENDING", "entry_reached": False, "opened_at": 2000,
                    "entry": 100, "stop_loss": 101, "tp1": 98, "tp2": 97, "tp3": 96,
                    "payload": {"strategy": "orderflow_momentum"},
                },
                {
                    "signal_id": "A3", "symbol": "SOL/USDT:USDT", "direction": "SHORT",
                    "status": "SL", "entry_reached": True, "opened_at": 1000,
                    "resolved_at": 1500, "entry": 75, "stop_loss": 76,
                    "tp1": 74, "tp2": 73, "tp3": 72, "realized_r": -1.0,
                    "payload": {"strategy": "smc"},
                },
            ]

    message = TelegramCommandService(Runtime(), "token", "chat").handle_islemler()
    assert "İŞLEMLERİM — 0" in message
    assert all(symbol not in message for symbol in ("BTC", "ETH", "SOL", "AVAX"))


def test_retired_setup_commands_are_aliases_to_islemler():
    from telegram_commands import get_command_by_name

    for name in ("mevcut", "setuplar", "takip"):
        command = get_command_by_name(name)
        assert command is not None
        assert command.handler == "handle_islemler"

def test_liquidity_failure_hides_raw_traceback():
    from types import SimpleNamespace

    runtime = SimpleNamespace(
        current_symbol=lambda: "BTC/USDT",
        analyze_symbol=lambda *args, **kwargs: {"ok": False, "error": "Traceback SECRET"},
    )
    message = TelegramCommandService(runtime, "token", "chat").handle_liquidity("BTC")
    assert "Analiz tamamlanamadı" in message
    assert "Traceback SECRET" not in message



def test_unfollowed_invalidated_signal_is_private(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    pool = SimpleNamespace(
        tracking=SimpleNamespace(tracked=lambda chat: []),
        get_best_setups=lambda **kwargs: [],
        get_active_setups=lambda: [],
        get_recent_history=lambda **kwargs: [],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)

    class Runtime:
        def signal_outcomes(self, **kwargs):
            return [{
                "signal_id": "OLD-AVAX",
                "symbol": "AVAX/USDT:USDT",
                "direction": "LONG",
                "status": "INVALIDATED",
                "entry_reached": False,
                "opened_at": 1000,
                "resolved_at": 2000,
                "invalidation_reason": "STRATEGY_STRUCTURE_BROKEN",
                "payload": {"strategy_id": "smc", "strategy": "SMC"},
            }]

    message = TelegramCommandService(Runtime(), "token", "chat").handle_islemler()
    assert "İŞLEMLERİM — 0" in message
    assert all(symbol not in message for symbol in ("BTC", "ETH", "SOL", "AVAX"))


def test_slow_symbol_analysis_does_not_block_telegram_command_worker(monkeypatch):
    import threading

    service = TelegramCommandService(object(), "token", "-100123")
    analysis_started = threading.Event()
    release_analysis = threading.Event()
    status_completed = threading.Event()
    replies = []

    def execute(command):
        if command.upper().startswith("/BTC"):
            analysis_started.set()
            assert release_analysis.wait(timeout=3)
            return "BTC analysis result"
        if command.lower().startswith("/durum"):
            status_completed.set()
            return "system status"
        raise AssertionError(command)

    monkeypatch.setattr(service, "execute_command", execute)
    monkeypatch.setattr(service, "_send_command_reply", replies.append)
    service._command_queue.put_nowait(("/BTC", "BTC"))
    service._command_queue.put_nowait(("/durum", "durum"))

    worker = threading.Thread(target=service._command_worker_loop, daemon=True)
    worker.start()
    try:
        assert analysis_started.wait(timeout=2)
        assert status_completed.wait(timeout=2), "status command was blocked by BTC analysis"
    finally:
        release_analysis.set()
        service.stop_flag.set()
        worker.join(timeout=2)
        with service._analysis_lock:
            analysis_threads = list(service._analysis_threads.values())
        for thread in analysis_threads:
            thread.join(timeout=2)

    assert "system status" in replies
    assert "BTC analysis result" in replies


def test_status_uses_actual_command_polling_thread_not_legacy_config(monkeypatch):
    import threading
    from atlas_runtime import AtlasRuntime
    from config import Config

    service = TelegramCommandService(object(), "token", "-100123")
    service._thread = threading.current_thread()

    runtime = object.__new__(AtlasRuntime)
    runtime._telegram_service = service
    runtime._current_signal = None
    runtime._error = None

    # The headless VPS intentionally disables the legacy Telegram poller.
    monkeypatch.setattr(Config, "TELEGRAM_POLLING_ENABLED", False, raising=False)
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "token", raising=False)

    status = runtime.telegram_status()
    assert status["polling_enabled"] is True
    assert status["service_running"] is True

    service.stop_flag.set()
    status = runtime.telegram_status()
    assert status["polling_enabled"] is False
    assert status["service_running"] is False


def test_trade_report_separates_today_history_and_preserves_cards(monkeypatch):
    import time
    from types import SimpleNamespace
    import telegram_command_service as telegram

    base = dict(direction="SHORT", entry=100, stop_loss=110, tp1=90, tp2=80, tp3=70)
    now = int(time.time() * 1000)
    rows = [
        ("AXIS", 1, "CLOSED", dict(base, status="SL", resolved_at=now, realized_r=-1)),
        ("OLD", 1, "CLOSED", dict(base, status="TP3", resolved_at=now-86400000, realized_r=2)),
        ("LAB", 1, "CLOSED", dict(base, status="SL", resolved_at=now, realized_r=-1)),
        ("CAP", 1, "AMBIGUOUS", dict(base, manual_review=True, ambiguity_reason="Eksik mum")),
        ("AVA", 1, "ACTIVE", dict(base, open_r=0.5)),
        ("ELSA", 1, "WAITING", base),
    ]
    tracking = SimpleNamespace(tracked=lambda _: rows)
    monkeypatch.setattr(telegram, "get_opportunity_pool", lambda: SimpleNamespace(tracking=tracking))
    report = TelegramCommandService(None, "offline", "chat").handle_islemler()
    sections = ["İŞLEMLERİM — 5", "Aktif (1)", "Giriş bekliyor (1)", "DOĞRULAMA BEKLİYOR (1)",
                "Bugün kapanan (2)", "Tüm dönem · kapanan işlemler", "Kapanan: 3"]
    assert [report.index(s) for s in sections] == sorted(report.index(s) for s in sections)
    assert report.index("OLD") > report.index("Önceki günlerde kapanan TP işlemleri (1/1)")
    assert "OLD · SHORT · TP3 alındı · +2.00R" in report and "Kalıcı inceleme" in report
    for block in report.split("\n\n"):
        if "Giriş:" in block:
            assert any(block in chunk for chunk in split_message(report, limit=180))


def test_partial_targets_survive_stop_and_midnight_in_both_reports(monkeypatch):
    import time
    from types import SimpleNamespace
    import telegram_command_service as telegram

    yesterday = int(time.time()*1000) - 86400000
    base = dict(direction="LONG", strategy="SMC", opened_at=yesterday-900000)
    rows = [
        ("OPEN", 1, "ACTIVE", dict(base, tps_hit=[1], status="PENDING")),
        ("EXIT", 1, "CLOSED", dict(base, tps_hit=[1, 2], status="SL", resolved_at=yesterday, realized_r=0.6)),
        ("OTHER", 1, "CLOSED", dict(base, status="SL", resolved_at=yesterday, realized_r=0.1)),
    ]
    tracking = SimpleNamespace(tracked=lambda _: rows)
    monkeypatch.setattr(telegram, "get_opportunity_pool", lambda: SimpleNamespace(tracking=tracking))
    service = TelegramCommandService(None, "offline", "chat")
    report = service.handle_islemler()
    assert "OPEN · LONG · TP1 alındı" in report
    assert "EXIT · LONG · TP1, TP2 alındı · Stop · +0.60R" in report
    assert "OTHER" not in report
    assert "TP1, TP2 alındı · Stop" in service.handle_history()
