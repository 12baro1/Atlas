import pytest

import atlas_service

from atlas_service import (
    DEFAULT_MAX_SYMBOLS,
    configured_max_symbols,
    select_live_symbols,
    load_startup_symbols,
)


def test_default_symbol_cap_is_top_300():
    assert configured_max_symbols(None) == DEFAULT_MAX_SYMBOLS == 300
    assert configured_max_symbols("") == 300


def test_symbol_cap_accepts_positive_values_and_clamps_unlimited():
    assert configured_max_symbols("12") == 12
    assert configured_max_symbols("0") == 300
    assert configured_max_symbols("500") == 300


@pytest.mark.parametrize("value", ["-1", "many", "1.5"])
def test_symbol_cap_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        configured_max_symbols(value)


def test_live_universe_contains_only_active_usdt_perpetual_swaps_and_applies_cap():
    markets = {
        "BTC/USDT:USDT": {"active": True, "swap": True},
        "ETH/USDT:USDT": {"active": True, "swap": True},
        "SOL/USDT:USDT": {"active": True, "swap": True},
        "XRP/USDT:USDT": {"active": False, "swap": True},
        "DOGE/USDT": {"active": True, "swap": False},
        "ADA/USDT:USDT": {"active": True, "swap": False},
        "AAPL/USDT:USDT": {"active": True, "swap": True, "info": {"contract_type": "stocks"}},
        "XAU/USDT:USDT": {"active": True, "swap": True, "info": {"contract_type": "metals"}},
    }

    symbols, stats = select_live_symbols(markets, max_symbols=2)

    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert stats["kept"] == 2
    assert stats["skipped_inactive"] == 1
    assert stats["skipped_not_swap"] == 1
    assert stats["skipped_non_crypto"] == 2
    assert stats["limited"] == 1


def test_zero_cap_keeps_all_matching_perpetual_swaps():
    markets = {
        "BTC/USDT:USDT": {"active": True, "swap": True},
        "ETH/USDT:USDT": {"active": True, "swap": True},
    }

    symbols, stats = select_live_symbols(markets, max_symbols=0)

    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert stats["kept"] == 2


def test_live_symbols_are_ranked_by_gateio_quote_volume_before_cap():
    class RankedExchange:
        def fetch_tickers(self, symbols=None):
            return {
                "BTC/USDT:USDT": {"quoteVolume": 100},
                "ETH/USDT:USDT": {"quoteVolume": 900},
                "SOL/USDT:USDT": {"quoteVolume": 500},
            }

    markets = {
        symbol: {"active": True, "swap": True}
        for symbol in ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
    }
    symbols, stats = select_live_symbols(markets, max_symbols=2, exchange_client=RankedExchange())

    assert symbols == ["ETH/USDT:USDT", "SOL/USDT:USDT"]
    assert stats["ranking_source"] == "gateio_24h_quote_volume"
    assert stats["limited"] == 1



def test_startup_inventory_retries_until_gateio_recovers():
    class FakeStopEvent:
        def is_set(self):
            return False

        def wait(self, _seconds):
            return False

    class FakeInventory:
        def __init__(self):
            self.refresh_calls = 0

        def refresh(self, force=True):
            assert force is True
            self.refresh_calls += 1
            if self.refresh_calls == 1:
                return {"symbol_count": 0, "last_error": "temporary timeout"}
            return {"symbol_count": 2, "last_error": None}

        def get_ranked_symbols(self, limit=None):
            assert limit == 2
            return ["BTC/USDT:USDT", "ETH/USDT:USDT"]

        def status(self):
            return {
                "symbol_count": 2,
                "last_error": None,
                "ranking_source": "gateio_24h_quote_volume",
            }

    class FakeLogger:
        def __init__(self):
            self.warnings = []

        def warning(self, message, *args):
            self.warnings.append((message, args))

    inventory = FakeInventory()
    logger = FakeLogger()
    symbols, status = load_startup_symbols(
        inventory,
        max_symbols=2,
        stop_event=FakeStopEvent(),
        logger=logger,
        retry_interval_seconds=1,
    )

    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert status["ranking_source"] == "gateio_24h_quote_volume"
    assert inventory.refresh_calls == 2
    assert logger.warnings


def test_startup_inventory_respects_shutdown_signal():
    class StoppedEvent:
        def is_set(self):
            return True

    class UnusedInventory:
        def refresh(self, force=True):
            raise AssertionError("must not make a network request after shutdown")

    symbols, status = load_startup_symbols(
        UnusedInventory(),
        max_symbols=10,
        stop_event=StoppedEvent(),
        logger=None,
    )
    assert symbols == []
    assert status == {}


def test_service_scheduler_clock_is_available():
    assert callable(atlas_service.time.monotonic)


def test_systemd_watchdog_protocol(monkeypatch):
    from unittest.mock import MagicMock, call
    from configparser import ConfigParser
    from pathlib import Path

    config = ConfigParser(interpolation=None)
    config.read(Path(atlas_service.__file__).parent / "deploy" / "atlas.service")
    service = config["Service"]
    assert service["Type"] == "notify" and service["WatchdogSec"] == "3min"
    assert service["Restart"] == "always" and config["Unit"]["StartLimitIntervalSec"] == "0"
    factory = MagicMock()
    monkeypatch.setattr(atlas_service.socket, "socket", factory)
    monkeypatch.setenv("NOTIFY_SOCKET", "@atlas-test")
    atlas_service.notify_systemd("READY=1")
    atlas_service.notify_systemd("WATCHDOG=1")
    sender = factory.return_value.__enter__.return_value
    assert sender.sendto.call_args_list == [call(b"READY=1", "\0atlas-test"), call(b"WATCHDOG=1", "\0atlas-test")]
    monkeypatch.delenv("NOTIFY_SOCKET")
    atlas_service.notify_systemd("WATCHDOG=1")
    assert factory.call_count == 2
