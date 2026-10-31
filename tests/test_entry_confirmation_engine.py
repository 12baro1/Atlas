from entry_confirmation_engine import EntryConfirmationEngine


def _entry(direction):
    return {"valid": True, "direction": direction, "entry": 100.0}


def _mtf():
    return {"valid": True}


def test_long_confirmation_requires_latest_bullish_break_and_bullish_fvg():
    structure = [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(_mtf(), structure, fvg, _entry("LONG"), current_price=100.0)
    assert result["confirmed"] is True


def test_short_confirmation_requires_latest_bearish_break_and_bearish_fvg():
    structure = [{"label": "LL", "bos": True, "choch": False, "direction": "BEARISH"}]
    fvg = [{"type": "BEARISH", "from": 103.0, "to": 105.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(_mtf(), structure, fvg, _entry("SHORT"), current_price=100.0)
    assert result["confirmed"] is True


def test_higher_low_label_without_break_is_not_an_entry_confirmation():
    structure = [{"label": "HL", "bos": False, "choch": False, "direction": None}]
    fvg = [{"type": "BULLISH", "filled": False}]
    result = EntryConfirmationEngine().confirm(_mtf(), structure, fvg, _entry("LONG"), current_price=100.0)
    assert result["confirmed"] is False
    assert "BOS/CHoCH" in result["reason"]


def test_wrong_direction_or_filled_fvg_does_not_confirm():
    structure = [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, [{"type": "BEARISH", "filled": False}], _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is False
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, [{"type": "BULLISH", "filled": True}], _entry("LONG")
    )
    assert result["confirmed"] is False
