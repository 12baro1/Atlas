"""Tests for ScannerEngine / StatisticsEngine / BacktestEngine receiving
real engine.analyze() result payloads."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanner_engine import ScannerEngine
from statistics_engine import StatisticsEngine
from backtest_engine import BacktestEngine


def make_payload(signal="LONG", confidence=90, rr=2.5, score=80):
    return {
        "symbol": "BTC/USDT",
        "signal": {"signal": signal, "confidence": confidence},
        "risk": {"entry": 100.0, "stop_loss": 99.0},
        "rr": {"rr": rr},
        "analysis": {
            "confluence": {"score": score, "reasons": ["FVG", "OTE"]},
            "market_phase": {"phase": "Expansion"},
            "setup_quality": {"grade": "A", "stars": 5, "setup": "OB_1H"},
        },
        "decision": {"action": "EXECUTE"},
    }


def test_scanner_engine_records_payload():
    scanner = ScannerEngine()
    scanner.add("BTC/USDT", make_payload())

    assert scanner.summary()["total"] == 1
    best = scanner.summary()["best"]
    assert best["direction"] == "LONG"


def test_scanner_engine_ignores_none():
    scanner = ScannerEngine()
    scanner.add("BTC/USDT", None)
    assert scanner.summary()["total"] == 0


def test_statistics_record_payload():
    stats = StatisticsEngine()
    stats.record_payload(make_payload(signal="SHORT", confidence=80, rr=3.0))

    summary = stats.summary()
    assert summary["total_signals"] == 1
    assert summary["short_signals"] == 1
    assert summary["average_rr"] == 3.0
    assert summary["average_confidence"] == 80.0


def test_backtest_engine_record_payload():
    bt = BacktestEngine()
    bt.record(make_payload(signal="LONG", rr=5.0))

    result = bt.statistics()
    assert result["total"] == 1