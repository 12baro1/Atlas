from choch_engine import CHOCHEngine


def test_bullish_choch_requires_alternating_confirmed_break_sequence():
    structure = [
        {"kind": "LOW", "label": "LL", "bos": False},
        {"kind": "HIGH", "label": "LH", "bos": False},
        {"kind": "LOW", "label": "HL", "bos": False},
        {"kind": "HIGH", "label": "HH", "bos": True},
    ]
    result = CHOCHEngine().detect(structure)
    assert result[-1]["choch"] is True
    assert result[-1]["direction"] == "BULLISH"


def test_bullish_choch_rejects_unconfirmed_higher_high():
    structure = [
        {"kind": "LOW", "label": "LL", "bos": False},
        {"kind": "HIGH", "label": "LH", "bos": False},
        {"kind": "LOW", "label": "HL", "bos": False},
        {"kind": "HIGH", "label": "HH", "bos": False},
    ]
    result = CHOCHEngine().detect(structure)
    assert not any(item["choch"] for item in result)


def test_choch_rejects_non_alternating_swing_sequence():
    structure = [
        {"kind": "LOW", "label": "LL", "bos": False},
        {"kind": "LOW", "label": "LH", "bos": False},
        {"kind": "LOW", "label": "HL", "bos": False},
        {"kind": "HIGH", "label": "HH", "bos": True},
    ]
    result = CHOCHEngine().detect(structure)
    assert not any(item["choch"] for item in result)


def test_bearish_choch_requires_confirmed_lower_low():
    structure = [
        {"kind": "HIGH", "label": "HH", "bos": False},
        {"kind": "LOW", "label": "HL", "bos": False},
        {"kind": "HIGH", "label": "LH", "bos": False},
        {"kind": "LOW", "label": "LL", "bos": True},
    ]
    result = CHOCHEngine().detect(structure)
    assert result[-1]["choch"] is True
    assert result[-1]["direction"] == "BEARISH"
