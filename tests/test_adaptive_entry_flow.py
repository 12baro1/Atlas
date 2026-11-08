from entry_confirmation_engine import EntryConfirmationEngine
from entry_engine import EntryEngine
from entry_optimizer import EntryOptimizer


def _structure():
    return [
        {"index": 1, "kind": "HIGH", "label": "HH", "price": 110.0, "bos": True, "direction": "BULLISH"},
        {"index": 2, "kind": "LOW", "label": "HL", "price": 89.5, "bos": False, "direction": None},
    ]


def test_trending_long_can_use_unmitigated_ob_overlapping_ote_without_fvg():
    entry = EntryEngine().generate(
        {"valid": True, "entry": "LONG"},
        _structure(),
        [],
        [{"type": "BULLISH", "low": 100.0, "high": 105.0, "mitigated": False, "strength": 80}],
        current_price=115.0,
        ote={"fib62": 102.0, "fib79": 108.0},
        market_regime={"regime": "TRENDING_UP"},
    )

    assert entry["valid"] is True
    assert entry["poi_source"] == "ORDER_BLOCK"
    assert entry["ote_confluence"] is True
    assert entry["entry"] == 105.0


def test_crossed_ob_is_replaced_by_another_actionable_ote_poi():
    entry = EntryEngine().generate(
        {"valid": True, "entry": "LONG"},
        _structure(),
        [],
        [
            {"type": "BULLISH", "low": 100.0, "high": 105.0, "mitigated": False, "strength": 90},
            {"type": "BULLISH", "low": 88.0, "high": 92.0, "mitigated": False, "strength": 70},
        ],
        current_price=95.0,
        ote={"fib62": 90.0, "fib79": 94.0},
        market_regime={"regime": "TRENDING_UP"},
    )

    assert entry["valid"] is True
    assert entry["poi_source"] == "ORDER_BLOCK"
    assert entry["poi_zone"] == {"low": 88.0, "high": 92.0}
    assert entry["entry"] == 92.0
    assert entry["entry_zone_crossed"] is False


def test_confirmation_accepts_ob_ote_confluence_without_fvg():
    entry = {
        "valid": True,
        "direction": "LONG",
        "entry": 105.0,
        "poi_source": "ORDER_BLOCK",
        "poi_zone": {"low": 100.0, "high": 105.0},
        "ote_confluence": True,
    }
    result = EntryConfirmationEngine().confirm(
        {"valid": True},
        [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}],
        [],
        entry,
        current_price=115.0,
    )

    assert result["confirmed"] is True
    assert result["poi_confirmation"] == "ORDER_BLOCK_OTE"


def test_ob_without_ote_confluence_remains_valid_structural_poi():
    entry = {
        "valid": True,
        "direction": "LONG",
        "entry": 105.0,
        "poi_source": "ORDER_BLOCK",
        "poi_zone": {"low": 100.0, "high": 105.0},
        "ote_confluence": False,
    }
    result = EntryConfirmationEngine().confirm(
        {"valid": True},
        [{"label": "HH", "bos": True, "choch": False, "direction": "BULLISH"}],
        [],
        entry,
        current_price=115.0,
    )

    assert result["confirmed"] is True
    assert result["poi_confirmation"] == "ORDER_BLOCK"
    assert "selected structural POI" in result["reason"]


def test_supportive_secondary_evidence_keeps_standard_confirmation():
    entry = {
        "valid": True, "direction": "LONG", "entry": 105.0,
        "stop_loss": 95.0, "entry_type": "LIMIT",
        "poi_zone": {"low": 100.0, "high": 110.0}, "checks": [],
    }
    EntryOptimizer().optimize(
        entry, current_price=120.0,
        trend={"trend": "BULLISH"},
        smt={"active": True, "direction": "BULLISH", "confidence": 85},
        cisd={"active": True, "direction": "BULLISH", "confidence": 80},
    )

    assert entry["confirmation_profile"]["mode"] == "EVIDENCE_BALANCE"
    assert "confirmation_requirements" not in entry


def test_material_secondary_conflict_changes_evidence_not_confirmation_gate():
    entry = {
        "valid": True, "direction": "LONG", "entry": 105.0,
        "stop_loss": 95.0, "entry_type": "LIMIT",
        "poi_zone": {"low": 100.0, "high": 110.0}, "checks": [],
    }
    EntryOptimizer().optimize(
        entry, current_price=120.0,
        trend={"trend": "BEARISH"},
        smt={"active": True, "direction": "BEARISH", "confidence": 90},
        orderbook={"active": True, "opposing": True, "direction": "LONG", "best_bid": 101.0},
    )

    assert entry["confirmation_profile"]["mode"] == "EVIDENCE_BALANCE"
    assert "confirmation_requirements" not in entry


def test_confirmation_exposes_optimizer_profile_and_requirements():
    entry = {
        "valid": False,
        "direction": "LONG",
        "confirmation_profile": {
            "mode": "CHOCH_OR_RECLAIM",
            "aligned_weight": 1.0,
            "opposing_weight": 2.0,
        },
        "confirmation_requirements": {
            "require_choch_or_reclaim": True,
            "reasons": ["unicorn_opposes"],
        },
    }
    result = EntryConfirmationEngine().confirm({}, [], [], entry)

    assert result["confirmation_profile"]["mode"] == "CHOCH_OR_RECLAIM"
    assert result["requirements"] == {}


def _bullish_fvg():
    return [{"type": "BULLISH", "from": 108.0, "to": 110.0, "filled": False}]



def test_counter_choch_is_advisory_and_does_not_veto_valid_poi():
    structure = [
        {"kind": "HIGH", "label": "HH", "price": 110.0, "bos": True, "direction": "BULLISH"},
        {"kind": "LOW", "label": "LL", "choch": True, "direction": "BEARISH"},
    ]
    entry = {"valid": True, "direction": "LONG", "entry": 105.0,
             "poi_source": "ORDER_BLOCK", "poi_zone": {"low": 103.0, "high": 106.0},
             "ote_confluence": True}
    result = EntryConfirmationEngine().confirm(
        {"valid": True}, structure, _bullish_fvg(), entry, current_price=105.0
    )
    assert result["confirmed"] is True
    assert result["15m_conflict"] is True
    assert result["advisory_only"] is True


def test_no_15m_break_does_not_veto_valid_poi():
    entry = {"valid": True, "direction": "SHORT", "entry": 95.0,
             "poi_source": "ORDER_BLOCK", "poi_zone": {"low": 94.0, "high": 97.0},
             "ote_confluence": True}
    result = EntryConfirmationEngine().confirm(
        {"valid": True}, [], [], entry, current_price=95.0
    )
    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "NO_15M_BREAK"
