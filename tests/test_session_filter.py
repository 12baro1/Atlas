from datetime import datetime, timezone

from session_filter import SessionFilter


def _timestamp(hour, weekday=1):
    # 2026-11-03 is Tuesday (weekday=1).
    return int(datetime(2026, 11, 3, hour, 0, tzinfo=timezone.utc).timestamp() * 1000)


def test_default_london_and_new_york_windows_do_not_claim_overlap():
    result = SessionFilter().check(_timestamp(12))
    assert result["newyork"] is True
    assert result["london"] is False
    assert result["overlap"] is False


def test_overlap_is_true_only_when_both_configured_windows_are_active(monkeypatch):
    import config

    monkeypatch.setattr(config.Config, "LONDON_START", 7)
    monkeypatch.setattr(config.Config, "LONDON_END", 14)
    monkeypatch.setattr(config.Config, "NEWYORK_START", 12)
    monkeypatch.setattr(config.Config, "NEWYORK_END", 16)

    result = SessionFilter().check(_timestamp(13))
    assert result["london"] is True
    assert result["newyork"] is True
    assert result["overlap"] is True


def test_weekend_is_not_an_active_trading_session():
    saturday = int(datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc).timestamp() * 1000)
    result = SessionFilter().check(saturday)
    assert result["weekend"] is True
    assert result["active"] is False
