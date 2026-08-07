import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entry_engine import EntryEngine


def test_entry_uses_mtf_direction_when_present():
    e = EntryEngine()
    result = e.generate(
        {"entry": "LONG"},
        [{"label": "LL", "price": 100, "kind": "LOW"}],
        [],
        [{"low": 90.0, "high": 95.0, "type": "BULLISH", "from": 92.0, "to": 95.0, "filled": False, "mitigated": False}],
        current_price=93.0,
    )
    assert result["direction"] == "LONG"


def test_uses_structure_direction_fallback_when_mtf_none():
    e = EntryEngine()
    result = e.generate(
        {"entry": "NONE"},
        [{"label": "HH", "price": 110, "kind": "HIGH"}, {"label": "HL", "price": 105, "kind": "LOW"}],
        [],
        [],
        current_price=106.0,
    )
    assert result["direction"] == "LONG"
    assert result["valid"] is True


def test_fallback_direction_respects_bearish_structure():
    e = EntryEngine()
    result = e.generate(
        {"entry": "NONE"},
        [{"label": "LL", "price": 90, "kind": "LOW"}, {"label": "LH", "price": 95, "kind": "HIGH"}],
        [],
        [],
        current_price=93.0,
    )
    assert result["direction"] == "SHORT"


def test_no_mtf_direction_and_no_structure_returns_invalid():
    e = EntryEngine()
    result = e.generate({"entry": "NONE"}, [], [], [], current_price=100.0)
    assert result["valid"] is False
    assert "No MTF direction" in result["reason"]