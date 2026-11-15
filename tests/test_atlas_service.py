import pytest

from atlas_service import (
    DEFAULT_MAX_SYMBOLS,
    configured_max_symbols,
    select_live_symbols,
)


def test_default_symbol_cap_is_lite_vps_friendly():
    assert configured_max_symbols(None) == DEFAULT_MAX_SYMBOLS == 20
    assert configured_max_symbols("") == 20


def test_symbol_cap_accepts_positive_and_unlimited_values():
    assert configured_max_symbols("12") == 12
    assert configured_max_symbols("0") == 0


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
    }

    symbols, stats = select_live_symbols(markets, max_symbols=2)

    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert stats["kept"] == 2
    assert stats["skipped_inactive"] == 1
    assert stats["skipped_not_swap"] == 1
    assert stats["limited"] == 1


def test_zero_cap_keeps_all_matching_perpetual_swaps():
    markets = {
        "BTC/USDT:USDT": {"active": True, "swap": True},
        "ETH/USDT:USDT": {"active": True, "swap": True},
    }

    symbols, stats = select_live_symbols(markets, max_symbols=0)

    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert stats["kept"] == 2
