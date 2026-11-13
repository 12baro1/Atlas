import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_engine import SignalEngine


def test_shared_specialist_event_only_changes_signal_confidence_once():
    shared_id = "shared-event:1700000000000"
    sweep = {
        "is_sweep": True,
        "event_id": shared_id,
        "strength_score": 80,
        "post_structure": {"confirmed": True},
    }
    smt = {"active": True, "event_id": shared_id, "direction": "BULLISH", "confidence": 90}
    unicorn = {"active": True, "event_id": shared_id, "direction": "BULLISH", "confidence": 90}
    cisd = {"active": True, "event_id": shared_id, "direction": "BULLISH", "confidence": 90}
    volume_profile = {"active": True, "event_id": shared_id, "direction": "BULLISH", "confidence": 90}
    institutional = {"active": True, "event_id": shared_id, "direction": "LONG", "confidence": 90}

    adjusted = SignalEngine()._adjust_confidence_by_liquidity_and_smt(
        50.0, "LONG", sweep, smt, unicorn, cisd, volume_profile, institutional
    )
    assert adjusted == 53.6
