from entry_confirmation_engine import EntryConfirmationEngine


def _entry(direction):
    return {
        "valid": True, "direction": direction, "entry": 100.0,
        "poi_source": "ORDER_BLOCK", "poi_zone": {"low": 95.0, "high": 97.0},
        "ote_confluence": False,
    }


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


def test_higher_low_label_without_break_remains_advisory_with_valid_poi():
    structure = [{"label": "HL", "bos": False, "choch": False, "direction": None}]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(_mtf(), structure, fvg, _entry("LONG"), current_price=100.0)
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "NO_15M_BREAK"


def test_wrong_direction_or_filled_fvg_is_advisory_when_structural_poi_is_valid():
    structure = [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, [{"type": "BEARISH", "from": 103.0, "to": 105.0, "filled": False}], _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True
    assert result["poi_confirmation"] == "ORDER_BLOCK"
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": True}], _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True


def test_fvg_on_wrong_side_does_not_veto_selected_structural_poi():
    structure = [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}]
    fvg = [{"type": "BULLISH", "from": 103.0, "to": 105.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True
    assert result["poi_confirmation"] == "ORDER_BLOCK"


def test_bullish_break_confirmation_survives_later_higher_low_pullback():
    structure = [
        {"index": 10, "label": "HH", "bos": True, "choch": False, "direction": "BULLISH"},
        {"index": 12, "label": "HL", "bos": False, "choch": False, "direction": None},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True


def test_bullish_confirmation_expires_after_newer_bearish_break():
    structure = [
        {"index": 10, "label": "HH", "bos": True, "choch": False, "direction": "BULLISH"},
        {"index": 12, "label": "HL", "bos": False, "choch": False, "direction": None},
        {"index": 14, "label": "LL", "bos": True, "choch": False, "direction": "BEARISH"},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True
    assert result["15m_conflict"] is True


def test_counter_bos_pullback_can_confirm_after_reclaimed_higher_low():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "bos": True, "direction": "BEARISH"},
        {"index": 14, "kind": "LOW", "label": "HL", "bos": False, "direction": None},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "COUNTER_DIRECTIONAL_EVIDENCE"


def test_counter_bos_without_reclaimed_swing_does_not_confirm():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "bos": True, "direction": "BEARISH"},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True
    assert result["15m_conflict"] is True


def test_counter_choch_is_advisory_for_valid_higher_timeframe_poi():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "bos": True, "choch": True, "direction": "BEARISH"},
        {"index": 14, "kind": "LOW", "label": "HL", "bos": False, "direction": None},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.0
    )
    assert result["confirmed"] is True
    assert result["15m_conflict"] is True


def test_counter_bos_can_confirm_when_price_reclaims_post_break_pullback_high():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "price": 102.0, "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "price": 98.0, "bos": True, "direction": "BEARISH"},
        {"index": 14, "kind": "HIGH", "label": "LH", "price": 101.0, "bos": False, "direction": None},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=101.5
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "COUNTER_DIRECTIONAL_EVIDENCE"


def test_counter_bos_is_not_accepted_until_price_reclaims_pullback_high():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "price": 102.0, "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "price": 98.0, "bos": True, "direction": "BEARISH"},
        {"index": 14, "kind": "HIGH", "label": "LH", "price": 101.0, "bos": False, "direction": None},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=100.5
    )
    assert result["confirmed"] is True
    assert result["15m_conflict"] is True


def test_short_counter_bos_can_confirm_after_price_reclaims_post_break_pullback_low():
    structure = [
        {"index": 10, "kind": "LOW", "label": "LL", "price": 98.0, "bos": True, "direction": "BEARISH"},
        {"index": 12, "kind": "HIGH", "label": "HH", "price": 102.0, "bos": True, "direction": "BULLISH"},
        {"index": 14, "kind": "LOW", "label": "HL", "price": 99.0, "bos": False, "direction": None},
    ]
    fvg = [{"type": "BEARISH", "from": 103.0, "to": 105.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("SHORT"), current_price=98.5
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "COUNTER_DIRECTIONAL_EVIDENCE"


def test_counter_bos_can_confirm_after_reclaiming_prior_structure_boundary_without_new_pivot():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "price": 102.0, "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "price": 98.0, "bos": True, "direction": "BEARISH"},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=102.5
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "COUNTER_DIRECTIONAL_EVIDENCE"


def test_counter_bos_is_rejected_until_prior_structure_boundary_is_reclaimed():
    structure = [
        {"index": 10, "kind": "HIGH", "label": "HH", "price": 102.0, "bos": True, "direction": "BULLISH"},
        {"index": 12, "kind": "LOW", "label": "LL", "price": 98.0, "bos": True, "direction": "BEARISH"},
    ]
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("LONG"), current_price=101.5
    )
    assert result["confirmed"] is True
    assert result["15m_conflict"] is True


def test_short_counter_bos_can_confirm_after_reclaiming_prior_structure_boundary_without_new_pivot():
    structure = [
        {"index": 10, "kind": "LOW", "label": "LL", "price": 98.0, "bos": True, "direction": "BEARISH"},
        {"index": 12, "kind": "HIGH", "label": "HH", "price": 102.0, "bos": True, "direction": "BULLISH"},
    ]
    fvg = [{"type": "BEARISH", "from": 103.0, "to": 105.0, "filled": False}]
    result = EntryConfirmationEngine().confirm(
        _mtf(), structure, fvg, _entry("SHORT"), current_price=97.5
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "COUNTER_DIRECTIONAL_EVIDENCE"



def test_conflicting_secondary_evidence_does_not_create_confirmation_gate():
    entry = _entry("LONG")
    entry["confirmation_requirements"] = {"require_choch_or_reclaim": True, "reasons": ["weak_volume"]}
    fvg = [{"type": "BULLISH", "from": 95.0, "to": 97.0, "filled": False}]

    bos_only = [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}]
    result = EntryConfirmationEngine().confirm(_mtf(), bos_only, fvg, entry, current_price=100.0)
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "DIRECTIONAL_EVIDENCE"

    choch = [{"label": "HH", "bos": True, "choch": True, "direction": "BULLISH"}]
    result = EntryConfirmationEngine().confirm(_mtf(), choch, fvg, entry, current_price=100.0)
    assert result["confirmed"] is True


def test_valid_order_block_poi_does_not_require_ote_confluence():
    entry = _entry("LONG")
    entry["poi_source"] = "ORDER_BLOCK"
    entry["ote_confluence"] = False
    result = EntryConfirmationEngine().confirm(_mtf(), [], [], entry, current_price=100.0)
    assert result["confirmed"] is True
    assert result["poi_confirmation"] == "ORDER_BLOCK"


def test_missing_structural_poi_remains_a_hard_confirmation_failure():
    entry = _entry("LONG")
    entry["poi_zone"] = None
    result = EntryConfirmationEngine().confirm(_mtf(), [], [], entry, current_price=100.0)
    assert result["confirmed"] is False
    assert result["reason"] == "Selected structural POI is unavailable"


def test_confirmed_sweep_reversal_is_not_vetoed_by_neutral_mtf():
    entry = _entry("LONG")
    entry.update({
        "direction_source": "CONFIRMED_SWEEP_REVERSAL",
        "confirmed_sweep_reversal": True,
    })
    result = EntryConfirmationEngine().confirm(
        {"valid": False, "entry": "NONE"},
        [],
        [],
        entry,
        current_price=100.0,
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "CONFIRMED_SWEEP_REVERSAL"
    assert result["direction_source"] == "CONFIRMED_SWEEP_REVERSAL"


def test_neutral_mtf_without_confirmed_sweep_reversal_still_blocks():
    entry = _entry("LONG")
    result = EntryConfirmationEngine().confirm(
        {"valid": False, "entry": "NONE"}, [], [], entry, current_price=100.0
    )
    assert result["confirmed"] is False
    assert "no confirmed sweep reversal" in result["reason"]
