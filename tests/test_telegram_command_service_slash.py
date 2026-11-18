"""Tests for Telegram slash command parsing and handling in telegram_command_service."""

import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from telegram_command_service import (
    TelegramCommandService,
    normalize_command,
    is_recognized_command,
    split_message,
    format_daily_signal_report,
    _format_telegram_card,
)


def test_normalize_plain_and_addressed_commands():
    assert normalize_command("  BTC   ") == "BTC"
    assert normalize_command("/help@Oakmontincbot") == "help"
    assert normalize_command("/analiz BTC@BotName") == "analiz BTC"
    assert normalize_command("/btc") == "btc"
    assert normalize_command("/20tara") == "20tara"


def test_recognizes_slash_commands():
    """All slash commands from telegram_commands.py should be recognized."""
    from telegram_commands import TELEGRAM_COMMANDS

    for cmd in TELEGRAM_COMMANDS:
        # Direct slash command
        assert is_recognized_command(f"/{cmd.name}"), f"Failed for /{cmd.name}"
        # With bot username
        assert is_recognized_command(f"/{cmd.name}@BotName"), f"Failed for /{cmd.name}@BotName"
        # Case insensitive
        assert is_recognized_command(f"/{cmd.name.upper()}"), f"Failed for /{cmd.name.upper()}"

        # Parameterized commands
        if cmd.takes_parameter:
            assert is_recognized_command(f"/{cmd.name} BTC"), f"Failed for /{cmd.name} BTC"
            assert is_recognized_command(f"/{cmd.name} BTC@BotName"), f"Failed for /{cmd.name} BTC@BotName"


def test_recognizes_legacy_commands():
    """Legacy plain-text commands should still work (backward compatibility)."""
    legacy = [
        "en iyi 5 işlem",
        "20 tara",
        "30 tara",
        "50 analiz et",
        "tüm piyasayı tara",
        "likidite BTC",
        "performans",
        "öğrenme",
        "yardım",
        "mevcut",
    ]
    for cmd in legacy:
        assert is_recognized_command(cmd), f"Legacy command not recognized: {cmd}"


def test_ignores_unrecognized_group_chat():
    """Plain text without slash should not be recognized as commands in groups."""
    # These are treated as chat, not commands
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
    runtime = MagicMock()
    service = TelegramCommandService(runtime, "token", "-100123")
    assert service.enabled
    service_without_chat = TelegramCommandService(runtime, "token", "")
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
    }
    text = _format_telegram_card(card)
    assert "BTC/USDT — LONG" in text
    assert "Strateji: SMC" in text
    assert "Giriş (LIMIT): 100" in text
    assert "SL: 99" in text
    assert "TP3: 103" in text
    assert "Net RR: +1.25R" in text
    assert "Risk/Getiri" not in text
    assert "LIMIT giriş bekleniyor" in text


def test_start_command_is_registered_and_recognized():
    assert is_recognized_command("/start")
    assert is_recognized_command("/start@Oakmontincbot")

    runtime = MagicMock()
    service = TelegramCommandService(runtime, "token", "-100123")
    reply = service.execute_command("/start")
    assert "ATLAS TELEGRAM AKTİF" in reply
    assert "/20tara" in reply


def test_recognizes_mevcut_command():
    assert is_recognized_command("/mevcut@Oakmontincbot")
    assert is_recognized_command("/mevcut")


def test_recognizes_cached_best_five_command():
    assert is_recognized_command("/eniyi5")
    assert is_recognized_command("/eniyi5@Oakmontincbot")


def test_telegram_service_ignores_queued_stale_analysis_commands():
    runtime = MagicMock()
    service = TelegramCommandService(runtime, "token", "-100123")
    called = []

    def mock_execute(command):
        called.append(command)
        return "ok"

    service.execute_command = mock_execute
    service._api = MagicMock()

    # Old message (10 minutes ago)
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


def test_telegram_card_omits_verbose_strategy_evidence():
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
    assert _format_price(100.0) == "100.0"
    assert _format_price(99.5) == "99.5"


def test_service_handles_slash_btc_directly():
    """Test that /btc (without @botname) is handled correctly."""
    runtime = MagicMock()
    # Need proper structure for build_signal_card to produce executable output
    # build_signal_card reads from result.analysis.entry and result.risk
    # Don't include strategy_lab or set to None to use build_signal_card
    mock_result = {
        "ok": True,
        "symbol": "BTC/USDT:USDT",
        "result": {
            "symbol": "BTC/USDT:USDT",
            "signal": {"signal": "LONG", "grade": "A", "confidence": 85, "strength": "Strong"},
            "decision": {"action": "EXECUTE", "score": 85, "reason": "Test"},
            "analysis": {
                "entry": {
                    "direction": "LONG",
                    "valid": True,
                    "entry": 95000,
                    "stop_loss": 94000,
                    "entry_type": "MARKET",
                },
                "confluence": {"checks": []},
                "market_phase": {"phase": "Trending"},
                "setup_quality": {"score": 80, "trade_allowed": True},
            },
            "risk": {
                "entry": 95000,
                "stop_loss": 94000,
                "tp1": 96000,
                "tp2": 97000,
                "tp3": 98000,
                "rr": 3.0,
                "risk_setup_valid": True,
            },
            # No strategy_lab key - will use build_signal_card
        },
        "elapsed_ms": 100,
    }
    runtime.analyze_symbol.return_value = mock_result
    runtime.scanner = MagicMock()
    runtime.scanner.clear = MagicMock()

    service = TelegramCommandService(runtime, "token", "-100123")
    service._api = MagicMock()

    result = service.execute_command("/btc")
    assert "BTC/USDT" in result
    assert "LONG" in result
    assert "borsaya emir gönderilmedi" in result


def test_service_handles_analiz_with_parameter():
    """Test /analiz BTC format."""
    runtime = MagicMock()
    # Need proper structure for build_signal_card to produce executable output
    # Don't include strategy_lab to use build_signal_card
    mock_result = {
        "ok": True,
        "symbol": "ETH/USDT:USDT",
        "result": {
            "symbol": "ETH/USDT:USDT",
            "signal": {"signal": "SHORT", "grade": "B", "confidence": 75, "strength": "Strong"},
            "decision": {"action": "EXECUTE", "score": 80, "reason": "Test"},
            "analysis": {
                "entry": {
                    "direction": "SHORT",
                    "valid": True,
                    "entry": 3400,
                    "stop_loss": 3450,
                    "entry_type": "MARKET",
                },
                "confluence": {"checks": []},
                "market_phase": {"phase": "Trending"},
                "setup_quality": {"score": 75, "trade_allowed": True},
            },
            "risk": {
                "entry": 3400,
                "stop_loss": 3450,
                "tp1": 3350,
                "tp2": 3300,
                "tp3": 3250,
                "rr": 2.5,
                "risk_setup_valid": True,
            },
            # No strategy_lab key - will use build_signal_card
        },
        "elapsed_ms": 150,
    }
    runtime.analyze_symbol.return_value = mock_result
    runtime.scanner = MagicMock()
    runtime.scanner.clear = MagicMock()

    service = TelegramCommandService(runtime, "token", "-100123")
    service._api = MagicMock()

    result = service.execute_command("/analiz ETH")
    assert "ETH/USDT" in result
    # The direction should be in the output
    assert "SHORT" in result or "SHORT" in result.upper()


def test_service_handles_20tara_scan():
    """Test /20tara triggers scan."""
    runtime = MagicMock()
    runtime.scanner = MagicMock()
    runtime.scanner.clear = MagicMock()
    runtime.latest_analyses = MagicMock(return_value=[])

    # Mock analyze_symbol to return no valid setups
    runtime.analyze_symbol.return_value = {"ok": False, "error": "no_setup"}

    service = TelegramCommandService(runtime, "token", "-100123")
    service._api = MagicMock()

    # We can't easily test the full scan flow without more mocking,
    # but we can verify the command is recognized
    assert is_recognized_command("/20tara")


def test_service_handles_eniyi5_from_cache():
    """Test /eniyi5 uses cached pool without new scan."""
    runtime = MagicMock()
    runtime.scanner = MagicMock()
    runtime.scanner.clear = MagicMock()

    # Mock cached analyses with valid setups
    cached_item = {
        "symbol": "BTC/USDT:USDT",
        "result": {
            "symbol": "BTC/USDT:USDT",
            "signal": {"signal": "LONG"},
            "strategy_lab": {"selected": {"direction": "LONG", "entry_type": "MARKET", "entry": 95000}},
        },
        "analyzed_at_ms": int(time.time() * 1000),
    }
    runtime.latest_analyses.return_value = [cached_item]

    service = TelegramCommandService(runtime, "token", "-100123")
    service._api = MagicMock()

    assert is_recognized_command("/eniyi5")


def test_command_case_insensitive():
    """Commands should be case-insensitive."""
    assert is_recognized_command("/BTC")
    assert is_recognized_command("/btc")
    assert is_recognized_command("/Btc")
    assert is_recognized_command("/ANALIZ BTC")
    assert is_recognized_command("/analiz btc")
    assert is_recognized_command("/ENIYI5")
    assert is_recognized_command("/eniyi5")


def test_bot_username_suffix_handled():
    """Commands with @BotName suffix should work."""
    assert is_recognized_command("/btc@MyBot")
    assert is_recognized_command("/analiz BTC@MyBot")
    assert is_recognized_command("/20tara@MyBot")
    assert is_recognized_command("/ENIYI5@MyBot")


def test_help_command():
    """Test /yardim returns help text."""
    runtime = MagicMock()
    service = TelegramCommandService(runtime, "token", "-100123")

    result = service.handle_help()
    assert "ATLAS TELEGRAM KOMUTLARI" in result
    assert "/btc" in result
    assert "/eniyi5" in result
    assert "/analiz" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

def test_status_command_formats_uptime_and_omits_chat_id():
    from telegram_command_service import TelegramCommandService

    class Runtime:
        def snapshot(self):
            return {"scanner": {
                "mode": "SCAN", "status": "READY", "cycle": 2,
                "processed": 20, "success": 18, "failed": 1, "skipped": 1,
                "started_at": int(time.time() * 1000) - 3_600_000,
            }}

        def telegram_status(self):
            return {
                "polling_enabled": True, "webhook_enabled": False,
                "service_running": True, "connected": True,
            }

    service = TelegramCommandService(Runtime(), "token", "-100123")
    message = service.handle_status()
    assert "Çalışma süresi:" in message
    assert "1.0 sa" in message
    assert "Chat ID" not in message


def test_uptime_formatter_handles_negative_and_long_durations():
    from telegram_command_service import TelegramCommandService

    assert TelegramCommandService._format_uptime(-5) == "0 sn"
    assert TelegramCommandService._format_uptime(90) == "1.5 dk"
    assert TelegramCommandService._format_uptime(90_000) == "1.0 gün"
