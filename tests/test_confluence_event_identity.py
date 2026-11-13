import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluence_engine import ConfluenceEngine


def test_shared_specialist_event_is_counted_once_in_confluence_score():
    shared_id = "shared-event:1700000000000"
    result = ConfluenceEngine().evaluate(
        mtf={"valid": True},
        trend={"trend": "BULLISH"},
        entry={"direction": "LONG", "valid": True},
        confirmation={"confirmed": True},
        premium_discount={"valid": True},
        liquidity_sweep={"is_sweep": False},
        ote={"valid": True},
        htf_orderblock={"valid": False},
        htf_fvg={"valid": False},
        killzone=False,
        session=False,
        smt={"active": True, "direction": "BULLISH", "confidence": 90, "event_id": shared_id},
        unicorn={"active": True, "direction": "BULLISH", "confidence": 90, "event_id": shared_id},
        cisd={"active": True, "direction": "BULLISH", "confidence": 90, "event_id": shared_id},
        volume_profile={"active": True, "direction": "BULLISH", "confidence": 90, "event_id": shared_id},
        institutional={"active": True, "direction": "LONG", "confidence": 90, "event_id": shared_id},
    )
    checks = result["checks"]
    assert any(item.startswith("✔ SMT BULLISH") for item in checks)
    assert not any(item.startswith("✔ Unicorn (") for item in checks)
    assert not any(item.startswith("✔ CISD BULLISH") for item in checks)
    assert not any(item.startswith("✔ Volume Profile BULLISH") for item in checks)
    assert not any(item.startswith("✔ Institutional Flow LONG") for item in checks)
    assert sum("duplicate event suppressed" in item for item in checks) == 4
