import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from universe_engine import select_symbols


def test_select_symbols_filters_and_sorts():
    markets = {
        "ETH/USDT:USDT": {"active": True, "swap": True},
        "BTC/USDT:USDT": {"active": True, "swap": True},
        "XRP/USDT:USDT": {"active": False, "swap": True},
        "DOGE/USDT": {"active": True, "swap": False},
    }

    symbols, stats = select_symbols(markets, suffix="/USDT:USDT", require_active=True)

    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert stats["total_markets"] == 4
    assert stats["skipped_suffix"] == 1
    assert stats["skipped_inactive"] == 1
    assert stats["kept"] == 2


def test_select_symbols_can_exclude_explicit_non_crypto_categories():
    markets = {
        "BTC/USDT:USDT": {"active": True, "swap": True, "info": {}},
        "ETH/USDT:USDT": {"active": True, "swap": True, "contract_type": "crypto"},
        "AAPL/USDT:USDT": {"active": True, "swap": True, "info": {"contract_type": "stocks"}},
        "XAU/USDT:USDT": {"active": True, "swap": True, "info": {"contract_type": "metals"}},
        "SPY/USDT:USDT": {"active": True, "swap": True, "info": {"contract_type": "indices"}},
    }
    symbols, stats = select_symbols(
        markets, suffix="/USDT:USDT", require_active=True,
        require_swap=True, require_crypto=True,
    )
    assert symbols == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert stats["skipped_non_crypto"] == 3


def test_select_symbols_applies_limit():
    markets = {
        "C/USDT:USDT": {"active": True},
        "A/USDT:USDT": {"active": True},
        "B/USDT:USDT": {"active": True},
    }

    symbols, stats = select_symbols(markets, suffix="/USDT:USDT", max_symbols=2)

    assert symbols == ["A/USDT:USDT", "B/USDT:USDT"]
    assert stats["limited"] == 1
    assert stats["kept"] == 2
