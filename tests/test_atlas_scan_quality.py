import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import atlas_tui


def test_scan_limit_is_always_bounded():
    assert atlas_tui._normalize_scan_limit("0") == 30
    assert atlas_tui._normalize_scan_limit("-5") == 30
    assert atlas_tui._normalize_scan_limit("not-a-number") == 30
    assert atlas_tui._normalize_scan_limit("12") == 12
    assert atlas_tui._normalize_scan_limit("500") == 100


def test_best_symbols_never_turn_zero_limit_into_full_market_scan(monkeypatch):
    symbols = [f"COIN{index}/USDT:USDT" for index in range(40)]

    class FakeExchange:
        def load_markets(self):
            return {}

        def fetch_tickers(self, requested):
            return {
                symbol: {"quoteVolume": float(index + 1)}
                for index, symbol in enumerate(requested)
            }

    monkeypatch.setattr(atlas_tui, "exchange", FakeExchange())
    monkeypatch.setattr(atlas_tui, "select_symbols", lambda **kwargs: (symbols, []))

    selected = atlas_tui._best_symbols(limit=0)
    assert len(selected) == 30
    assert selected[0] == symbols[-1]


def test_best_symbols_reject_non_finite_volume(monkeypatch):
    symbols = ["GOOD/USDT:USDT", "NAN/USDT:USDT", "INF/USDT:USDT"]

    class FakeExchange:
        def load_markets(self):
            return {}

        def fetch_tickers(self, requested):
            return {
                "GOOD/USDT:USDT": {"quoteVolume": 10.0},
                "NAN/USDT:USDT": {"quoteVolume": float("nan")},
                "INF/USDT:USDT": {"quoteVolume": float("inf")},
            }

    monkeypatch.setattr(atlas_tui, "exchange", FakeExchange())
    monkeypatch.setattr(atlas_tui, "select_symbols", lambda **kwargs: (symbols, []))

    assert atlas_tui._best_symbols(limit=30) == ["GOOD/USDT:USDT"]


def test_rank_metrics_reject_non_finite_numbers():
    assert atlas_tui._finite_number(float("nan")) is None
    assert atlas_tui._finite_number(float("inf")) is None
    assert atlas_tui._finite_number("2.5") == 2.5
