"""trace_context birim testleri: tek analiz = tek kimlik, gözlemsel aşamalar."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import trace_context as tc


def test_new_trace_id_is_unique_and_timestamped():
    first = tc.new_trace_id(now_ms=1_700_000_000_000)
    second = tc.new_trace_id(now_ms=1_700_000_000_000)

    assert first.startswith("trace-1700000000000-")
    assert second.startswith("trace-1700000000000-")
    assert first != second


def test_ensure_trace_generates_once_and_stays_stable_within_analysis():
    data = {"symbol": "BTC/USDT:USDT"}
    trace = tc.ensure_trace(data)

    assert trace["trace_id"].startswith("trace-")
    assert data["trace_id"] == trace["trace_id"]
    # Aynı analizde tekrar çağrı yeni kimlik ÜRETMEZ.
    again = tc.ensure_trace(data)
    assert again["trace_id"] == trace["trace_id"]
    assert tc.trace_id(data) == trace["trace_id"]


def test_ensure_trace_preserves_existing_trace_id():
    data = {"symbol": "BTC/USDT:USDT", "trace_id": "trace-123-aaaa"}
    trace = tc.ensure_trace(data)

    assert trace["trace_id"] == "trace-123-aaaa"
    assert data["trace_id"] == "trace-123-aaaa"


def test_ensure_trace_preserves_trace_dict_id_and_existing_stages():
    data = {"trace": {"trace_id": "trace-9-bbbb", "stages": [{"stage": "DATA_SOURCE"}]}}
    trace = tc.ensure_trace(data)

    assert trace["trace_id"] == "trace-9-bbbb"
    assert trace["stages"][0]["stage"] == "DATA_SOURCE"
    assert data["trace_id"] == "trace-9-bbbb"


def test_ensure_trace_ignores_non_dict_payloads():
    assert tc.ensure_trace(None) is None
    assert tc.ensure_trace("not-a-dict") is None
    assert tc.trace_id(None) is None


def test_trace_id_reads_without_creating():
    data = {"symbol": "BTC/USDT:USDT"}
    assert tc.trace_id(data) is None
    assert "trace_id" not in data
    assert "trace" not in data


def test_record_stage_captures_pipeline_fields():
    data = {"symbol": "BTC/USDT:USDT"}
    tc.ensure_trace(data)
    entry = tc.record_stage(
        data,
        tc.STAGE_COMMON_FILTER,
        source="COMMON_FILTER",
        timestamp_ms=1_700_000_000_000,
        freshness="UNKNOWN",
        availability="REJECTED",
        reason="TEST_REJECT",
        strategy="trend_pullback",
        setup_id="setup-trend_pullback-01",
        filter_result="REJECTED",
        decision=None,
        detail={"checked": "geometry"},
    )

    assert entry["stage"] == "COMMON_FILTER"
    assert entry["trace_id"] == data["trace_id"]
    assert entry["symbol"] == "BTC/USDT:USDT"
    assert entry["timestamp_ms"] == 1_700_000_000_000
    assert entry["filter_result"] == "REJECTED"
    assert entry["setup_id"] == "setup-trend_pullback-01"
    assert entry["detail"] == {"checked": "geometry"}
    # None alanlar kayda yazılmaz.
    assert "decision" not in entry
    stages = data["trace"]["stages"]
    assert len(stages) == 1 and stages[0] is entry


def test_record_stage_defaults_timestamp_and_creates_trace_lazily():
    data = {"symbol": "BTC/USDT:USDT"}
    entry = tc.record_stage(data, tc.STAGE_STRATEGY_SETUP, strategy="smc")

    assert entry["trace_id"] == data["trace_id"]
    assert entry["timestamp_ms"] > 0
    assert entry["strategy"] == "smc"


def test_record_stage_caps_stage_count():
    data = {"symbol": "BTC/USDT:USDT"}
    tc.ensure_trace(data)
    for _ in range(tc.MAX_STAGES + 40):
        tc.record_stage(data, "DATA_SOURCE")

    assert len(data["trace"]["stages"]) == tc.MAX_STAGES


def test_stage_constants_cover_the_full_pipeline():
    assert tc.STAGE_DATA_SOURCE == "DATA_SOURCE"
    assert tc.STAGE_DATA_COLLECTION == "DATA_COLLECTION"
    assert tc.STAGE_DATA_NORMALIZATION == "DATA_NORMALIZATION"
    assert tc.STAGE_SHARED_MARKET_EVIDENCE == "SHARED_MARKET_EVIDENCE"
    assert tc.STAGE_SPECIALIST_MOTORS == "SPECIALIST_MOTORS"
    assert tc.STAGE_STRATEGY_SETUP == "STRATEGY_SETUP"
    assert tc.STAGE_COMMON_FILTER == "COMMON_FILTER"
    assert tc.STAGE_FINAL_DECISION == "FINAL_DECISION"
    assert tc.STAGE_SIGNAL_OUTPUT == "SIGNAL_OUTPUT"
