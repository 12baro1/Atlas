import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_tui


def test_best_symbols_ranks_active_usdt_markets_by_quote_volume(monkeypatch):
    markets = {
        "BRC/USDT:USDT": {"active": True, "swap": True},
        "BTC/USDT:USDT": {"active": True, "swap": True},
        "ETH/USDT:USDT": {"active": True, "swap": True},
        "DELISTED/USDT:USDT": {"active": False, "swap": True},
        "BTC/USD:USD": {"active": True, "swap": True},
    }
    tickers = {
        "BRC/USDT:USDT": {"quoteVolume": 1200},
        "BTC/USDT:USDT": {"quoteVolume": 9000},
        "ETH/USDT:USDT": {"quoteVolume": 4000},
        "DELISTED/USDT:USDT": {"quoteVolume": 50000},
    }
    monkeypatch.setattr(atlas_tui.exchange, "load_markets", lambda: markets)
    monkeypatch.setattr(atlas_tui.exchange, "fetch_tickers", lambda symbols: tickers)

    assert atlas_tui._best_symbols(limit=2) == ["BTC/USDT:USDT", "ETH/USDT:USDT"]


def test_best_symbols_ignores_missing_or_invalid_volumes(monkeypatch):
    markets = {
        "BRC/USDT:USDT": {"active": True},
        "BTC/USDT:USDT": {"active": True},
    }
    tickers = {
        "BRC/USDT:USDT": {"quoteVolume": None},
        "BTC/USDT:USDT": {"quoteVolume": "not-a-number"},
    }
    monkeypatch.setattr(atlas_tui.exchange, "load_markets", lambda: markets)
    monkeypatch.setattr(atlas_tui.exchange, "fetch_tickers", lambda symbols: tickers)

    assert atlas_tui._best_symbols(limit=5) == []


def test_symbol_input_accepts_tickers_and_usdt_perpetual_symbols():
    assert atlas_tui._is_symbol_input("BTC")
    assert atlas_tui._is_symbol_input("1000PEPE")
    assert atlas_tui._is_symbol_input("btc/usdt:usdt")
    assert atlas_tui._is_symbol_input("ETH/USDT")


def test_symbol_input_rejects_free_text_and_malformed_symbols():
    assert not atlas_tui._is_symbol_input("bana işlem ver")
    assert not atlas_tui._is_symbol_input("BTC USDT")
    assert not atlas_tui._is_symbol_input("")
    assert not atlas_tui._is_symbol_input("BTC; rm -rf")
