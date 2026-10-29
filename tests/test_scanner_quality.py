import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanner_engine import ScannerEngine


def _payload(symbol, decision, score):
    return {
        "analysis": {
            "confluence": {"score": score, "reasons": []},
            "setup_quality": {"grade": "A", "stars": 4, "setup": "SMC"},
            "market_phase": {"phase": "Trending"},
            "entry": {"entry_type": "LIMIT"},
        },
        "signal": {"signal": "LONG", "confidence": 90},
        "risk": {
            "entry": 100.0,
            "stop_loss": 99.0,
            "tp1": 101.0,
            "tp2": 102.0,
            "tp3": 103.0,
            "risk_setup_valid": True,
        },
        "decision": {"action": decision},
        "rr": {"rr": 3.0},
    }


def test_scanner_only_counts_approved_complete_setups_as_executable():
    scanner = ScannerEngine()
    scanner.add("BTC/USDT", _payload("BTC/USDT", "SKIP", 99))
    scanner.add("ETH/USDT", _payload("ETH/USDT", "EXECUTE", 70))

    summary = scanner.summary()

    assert summary["total"] == 2
    assert [item["symbol"] for item in summary["executable"]] == ["ETH/USDT"]
    assert scanner.results()[0]["symbol"] == "ETH/USDT"


def test_scanner_does_not_mark_missing_targets_as_tradable():
    scanner = ScannerEngine()
    payload = _payload("SOL/USDT", "EXECUTE", 99)
    payload["risk"]["tp2"] = None
    scanner.add("SOL/USDT", payload)

    assert scanner.summary()["executable"] == []
