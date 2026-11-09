import math

from statistics_engine import StatisticsEngine


def test_record_payload_ignores_non_finite_metrics_without_poisoning_averages():
    engine = StatisticsEngine()
    engine.record_payload({
        "signal": {"signal": "LONG", "confidence": float("nan")},
        "rr": {"rr": float("inf")},
    })
    engine.record_payload({
        "signal": {"signal": "SHORT", "confidence": 80},
        "rr": {"rr": 2.5},
    })

    result = engine.summary()
    assert result["total_signals"] == 2
    assert result["long_signals"] == 1
    assert result["short_signals"] == 1
    assert result["average_rr"] == 1.25
    assert result["average_confidence"] == 40


def test_record_accepts_zero_rr_and_rejects_non_dictionary_payloads():
    engine = StatisticsEngine()
    engine.record(None)
    engine.record_payload(None)
    engine.record({"direction": "LONG", "rr": 0, "signal": {"confidence": 0}})

    result = engine.summary()
    assert result["total_signals"] == 1
    assert result["average_rr"] == 0
    assert result["average_confidence"] == 0
    assert math.isfinite(result["average_rr"])


def test_ingest_journal_keeps_calibration_gap_contract():
    result = StatisticsEngine().ingest_journal({
        "summary": {"total_trades": 4, "average_r": 1.2},
        "confidence_quality": {"calibration_gap": 7.5},
    })
    assert result["average_confidence"] == 7.5
