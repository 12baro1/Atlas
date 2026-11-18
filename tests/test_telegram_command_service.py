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


def test_recognizes_terminal_commands():
    for command in (
        "/BTC",
        "/ETH",
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
    assert "A4" in report


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
    assert "Strateji: orderflow_momentum" in message
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
    assert "Stop: 95,700" in report
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
    from types import SimpleNamespace

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
        get_validated_setups=lambda **kwargs: [candidate],
        get_active_setups=lambda: [],
    )
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)
    service = TelegramCommandService(SimpleNamespace(), "token", "chat")
    message = service.handle_setuplar()
    assert "BTC/USDT LONG" in message
    assert "TP1: 102" in message
    assert "Durum: VALIDATED" in message


def test_mevcut_includes_validated_pool_setups_not_in_signal_journal(monkeypatch):
    from types import SimpleNamespace
    import telegram_command_service as telegram_module

    candidate = SimpleNamespace(
        symbol="SOL/USDT:USDT", direction="SHORT", strategy_name="Mean Reversion",
        entry_price=150.0, stop_loss=153.0, tp1=147.0, tp2=144.0,
        tp3=141.0, net_rr_after_costs=2.0,
    )
    pool = SimpleNamespace(get_validated_setups=lambda **kwargs: [candidate])
    monkeypatch.setattr(telegram_module, "get_opportunity_pool", lambda: pool)

    class Runtime:
        def signal_outcomes(self, **kwargs):
            return []

    service = TelegramCommandService(Runtime(), "token", "chat")
    message = service.handle_mevcut()
    assert "SOL/USDT SHORT" in message
    assert "henüz sinyal sonucu takibine alınmamış" in message
