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


def test_ob_without_ote_confluence_does_not_replace_fvg_confirmation():
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

    assert result["confirmed"] is False
    assert "OB+OTE" in result["reason"]


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

    assert entry["confirmation_profile"]["mode"] == "DIRECTIONAL_BREAK"
    assert "confirmation_requirements" not in entry


def test_material_secondary_conflict_requires_choch_or_reclaim():
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

    assert entry["confirmation_profile"]["mode"] == "CHOCH_OR_RECLAIM"
    assert entry["confirmation_requirements"]["require_choch_or_reclaim"] is True


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
    assert result["requirements"]["require_choch_or_reclaim"] is True


def _bullish_fvg():
    return [{"type": "BULLISH", "from": 108.0, "to": 110.0, "filled": False}]


def test_counter_choch_can_confirm_long_only_after_recovery_and_reclaim():
    structure = [
        {"kind": "HIGH", "label": "HH", "price": 110.0, "bos": True, "direction": "BULLISH"},
        {"kind": "LOW", "label": "HL", "price": 100.0},
        {"kind": "LOW", "label": "LL", "choch": True, "direction": "BEARISH"},
        {"kind": "LOW", "label": "HL", "price": 104.0},
        {"kind": "HIGH", "label": "HH", "price": 112.0},
    ]
    entry = {"valid": True, "direction": "LONG", "entry": 105.0,
             "poi_source": "ORDER_BLOCK", "poi_zone": {"low": 103.0, "high": 106.0},
             "ote_confluence": True}
    engine = EntryConfirmationEngine()

    not_reclaimed = engine.confirm(
        {"valid": True}, structure, _bullish_fvg(), entry, current_price=111.0
    )
    assert not_reclaimed["confirmed"] is False
    assert "reclaim level" in not_reclaimed["reason"]

    reclaimed = engine.confirm(
        {"valid": True}, structure, _bullish_fvg(), entry, current_price=113.0
    )
    assert reclaimed["confirmed"] is True
    assert reclaimed["confirmation_mode"] == "reclaimed_counter_choch"
    assert reclaimed["reentry_triggered"] is True


def test_counter_choch_can_confirm_short_only_after_recovery_and_reclaim():
    structure = [
        {"kind": "LOW", "label": "LL", "price": 90.0, "bos": True, "direction": "BEARISH"},
        {"kind": "HIGH", "label": "LH", "price": 100.0},
        {"kind": "HIGH", "label": "HH", "choch": True, "direction": "BULLISH"},
        {"kind": "HIGH", "label": "LH", "price": 96.0},
        {"kind": "LOW", "label": "LL", "price": 88.0},
    ]
    entry = {"valid": True, "direction": "SHORT", "entry": 95.0,
             "poi_source": "ORDER_BLOCK", "poi_zone": {"low": 94.0, "high": 97.0},
             "ote_confluence": True}
    fvg = [{"type": "BEARISH", "from": 90.0, "to": 92.0, "filled": False}]

    result = EntryConfirmationEngine().confirm(
        {"valid": True}, structure, fvg, entry, current_price=87.0
    )

    assert result["confirmed"] is True
    assert result["confirmation_mode"] == "reclaimed_counter_choch"
    assert result["reentry_triggered"] is True


def test_counter_choch_without_post_reversal_recovery_is_rejected():
    structure = [
        {"kind": "HIGH", "label": "HH", "price": 110.0, "bos": True, "direction": "BULLISH"},
        {"kind": "LOW", "label": "LL", "choch": True, "direction": "BEARISH"},
        {"kind": "HIGH", "label": "HH", "price": 112.0},
    ]
    entry = {"valid": True, "direction": "LONG", "entry": 105.0,
             "poi_source": "ORDER_BLOCK", "poi_zone": {"low": 103.0, "high": 106.0},
             "ote_confluence": True}

    result = EntryConfirmationEngine().confirm(
        {"valid": True}, structure, _bullish_fvg(), entry, current_price=113.0
    )

    assert result["confirmed"] is False
    assert "recovery swing" in result["reason"]
