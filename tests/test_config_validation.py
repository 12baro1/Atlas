"""Config doğrulama sistemi testleri."""

import logging

from config import Config


def _silent_logger():
    logger = logging.getLogger("atlas.test.config")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL)
    return logger


def test_validate_defaults_passes():
    # Varsayılan Config doğrulamadan geçmeli (hata olmamalı).
    errors, warnings = Config.validate(logger=_silent_logger())
    assert errors == 0


def test_validate_rejects_negative_max_position_size(monkeypatch):
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", -1.0)
    errors, warnings = Config.validate(logger=_silent_logger())
    assert errors >= 1


def test_validate_rejects_bad_leverage_range(monkeypatch):
    monkeypatch.setattr(Config, "AUTO_TRADING_MIN_LEVERAGE", 20)
    monkeypatch.setattr(Config, "AUTO_TRADING_MAX_LEVERAGE", 5)
    errors, _ = Config.validate(logger=_silent_logger())
    assert errors >= 1


def test_validate_autotrading_requires_keys(monkeypatch):
    monkeypatch.setattr(Config, "AUTO_TRADING_ENABLED", True)
    monkeypatch.setattr(Config, "BYBIT_API_KEY", "")
    monkeypatch.setattr(Config, "BYBIT_API_SECRET", "")
    monkeypatch.setattr(Config, "BYBIT_TESTNET", True)
    monkeypatch.setattr(Config, "BYBIT_DEMO_TRADING", False)
    errors, _ = Config.validate(logger=_silent_logger())
    assert errors >= 1


def test_validate_or_raise_raises_on_error(monkeypatch):
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", -5.0)
    try:
        Config.validate_or_raise(logger=_silent_logger())
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_validate_or_raise_ok_on_clean(monkeypatch):
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1000.0)
    assert Config.validate_or_raise(logger=_silent_logger()) is True


def test_validate_warns_on_live_autotrading(monkeypatch):
    monkeypatch.setattr(Config, "AUTO_TRADING_ENABLED", True)
    monkeypatch.setattr(Config, "BYBIT_API_KEY", "k")
    monkeypatch.setattr(Config, "BYBIT_API_SECRET", "s")
    monkeypatch.setattr(Config, "BYBIT_TESTNET", False)
    monkeypatch.setattr(Config, "BYBIT_DEMO_TRADING", False)
    errors, warnings = Config.validate(logger=_silent_logger())
    assert errors == 0
    assert warnings >= 1


def test_validate_rejects_bad_session_hours(monkeypatch):
    monkeypatch.setattr(Config, "LONDON_START", 30)
    monkeypatch.setattr(Config, "LONDON_END", 40)
    errors, _ = Config.validate(logger=_silent_logger())
    assert errors >= 1