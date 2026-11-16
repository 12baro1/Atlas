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
    assert "Verilen setup: 5" in report
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
    }
    text = _format_telegram_card(card)
    assert "Strateji: SMC" in text
    assert "Yön: LONG | Emir: LIMIT" in text
    assert "Giriş: 100.0" in text
    assert "SL: 99.0" in text
    assert "TP3: 103.0" in text
    assert "Net RR: +1.25R" in text
    assert "motor" not in text.lower()


def test_recognizes_mevcut_command():
    assert is_recognized_command("/mevcut@Oakmontincbot")


def test_recognizes_cached_best_five_command():
    assert is_recognized_command("/eniyi5")
    assert is_recognized_command("/eniyi5@Oakmontincbot")



def test_telegram_service_ignores_queued_stale_analysis_commands(monkeypatch):
    service = TelegramCommandService(object(), "token", "-100123")
    called = []
    monkeypatch.setattr(service, "execute_command", lambda command: called.append(command) or "ok")
    monkeypatch.setattr(service, "_api", lambda *args, **kwargs: None)

    service._handle_update({
        "update_id": 10,
        "message": {
            "date": int(time.time()) - 600,
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
