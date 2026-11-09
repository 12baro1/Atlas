import json

from economic_news_engine import EconomicNewsFilter


def test_evaluate_skips_malformed_event_rows_without_crashing():
    result = EconomicNewsFilter().evaluate(
        timestamp_ms=1_800_000_000_000,
        events=[
            None,
            "bad-row",
            {"impact": "HIGH", "title": "FOMC", "timestamp_ms": 1_800_000_000_000},
        ],
    )
    assert result["active"] is True
    assert len(result["blocking_events"]) == 1


def test_zero_timestamp_is_not_replaced_by_current_time():
    result = EconomicNewsFilter().evaluate(
        timestamp_ms=0,
        events=[{"impact": "HIGH", "title": "CPI", "timestamp": 0}],
    )
    assert result["active"] is True


def test_event_file_with_non_list_events_fails_closed(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(json.dumps({"events": "not-a-list"}), encoding="utf-8")
    engine = EconomicNewsFilter(events_path=path)
    assert engine.evaluate(timestamp_ms=0)["trade_allowed"] is True


def test_invalid_event_timestamps_are_ignored():
    result = EconomicNewsFilter().evaluate(
        timestamp_ms=1_800_000_000_000,
        events=[
            {"impact": "HIGH", "title": "FOMC", "timestamp_ms": "nan"},
            {"impact": "HIGH", "title": "CPI", "timestamp_ms": float("inf")},
        ],
    )
    assert result["trade_allowed"] is True
    assert result["blocking_events"] == []
