from engine import AtlasEngine
from ote_engine import OTEEngine


def test_long_ote_uses_latest_confirmed_higher_low_to_higher_high_leg():
    structure = [
        {"index": 10, "kind": "LOW", "label": "HL", "price": 90},
        {"index": 20, "kind": "HIGH", "label": "HH", "price": 110},
        {"index": 30, "kind": "LOW", "label": "HL", "price": 100},
        {"index": 40, "kind": "HIGH", "label": "HH", "price": 120},
    ]
    assert AtlasEngine._h4_ote_range(None, structure, "LONG") == (120.0, 100.0)


def test_short_ote_uses_latest_lower_high_to_lower_low_leg():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "LH", "price": 120},
        {"index": 20, "kind": "LOW", "label": "LL", "price": 100},
        {"index": 30, "kind": "HIGH", "label": "LH", "price": 110},
        {"index": 40, "kind": "LOW", "label": "LL", "price": 90},
    ]
    assert AtlasEngine._h4_ote_range(None, structure, "SHORT") == (110.0, 90.0)


def test_missing_confirmed_4h_leg_returns_invalid_ote_without_crashing():
    result = OTEEngine().detect(None, None, 100.0, "LONG")
    assert result["valid"] is False
    assert result["fib62"] is None


def test_later_lower_low_invalidates_old_bullish_ote_leg():
    structure = [
        {"index": 10, "kind": "LOW", "label": "HL", "price": 90},
        {"index": 20, "kind": "HIGH", "label": "HH", "price": 110},
        {"index": 30, "kind": "LOW", "label": "LL", "price": 88},
    ]
    assert AtlasEngine._h4_ote_range(None, structure, "LONG") == (None, None)


def test_later_higher_high_invalidates_old_bearish_ote_leg():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "LH", "price": 110},
        {"index": 20, "kind": "LOW", "label": "LL", "price": 90},
        {"index": 30, "kind": "HIGH", "label": "HH", "price": 112},
    ]
    assert AtlasEngine._h4_ote_range(None, structure, "SHORT") == (None, None)
