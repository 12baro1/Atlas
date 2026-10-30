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


def test_supported_input_accepts_best_trade_commands():
    for command in ("işlem ver", "islem ver", "en iyi işlem", "best trade"):
        assert atlas_tui._is_supported_input(command)


def test_supported_input_rejects_unknown_free_text():
    assert not atlas_tui._is_supported_input("bana işlem ver")


def test_parse_numeric_scan_commands():
    assert atlas_tui._parse_scan_command("50 analiz et") == (50, 5)
    assert atlas_tui._parse_scan_command("100 tara") == (100, 5)
    assert atlas_tui._parse_scan_command("ilk 75 piyasayı tara") == (75, 5)


def test_parse_top_n_commands():
    assert atlas_tui._parse_scan_command("en iyi 5 işlem") == (100, 5)
    assert atlas_tui._parse_scan_command("10 işlem") == (100, 10)
    assert atlas_tui._parse_scan_command("en iyi 25 işlem") == (100, 20)


def test_parse_full_market_commands():
    assert atlas_tui._parse_scan_command("tüm piyasayı tara") == (None, 5)
    assert atlas_tui._parse_scan_command("tum piyasayi tara") == (None, 5)
    assert atlas_tui._parse_scan_command("full scan") == (None, 5)


def test_parse_scan_command_caps_numeric_requests(monkeypatch):
    assert atlas_tui._parse_scan_command("999 analiz et") == (500, 5)


def test_best_symbols_can_return_entire_eligible_universe(monkeypatch):
    markets = {
        "BTC/USDT:USDT": {"active": True, "swap": True},
        "ETH/USDT:USDT": {"active": True, "swap": True},
        "BRC/USDT:USDT": {"active": True, "swap": True},
    }
    tickers = {
        "BTC/USDT:USDT": {"quoteVolume": 9000},
        "ETH/USDT:USDT": {"quoteVolume": 4000},
        "BRC/USDT:USDT": {"quoteVolume": 1200},
    }
    monkeypatch.setattr(atlas_tui.exchange, "load_markets", lambda: markets)
    monkeypatch.setattr(atlas_tui.exchange, "fetch_tickers", lambda symbols: tickers)

    assert atlas_tui._best_symbols(limit=None) == [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "BRC/USDT:USDT"
    ]
