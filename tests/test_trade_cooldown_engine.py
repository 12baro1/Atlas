from trade_cooldown_engine import TradeCooldownEngine


def test_explicit_zero_timestamp_is_preserved_for_register_and_evaluate(monkeypatch):
    engine = TradeCooldownEngine()
    engine.register_signal("BTC/USDT:USDT", "LONG", now_ts=0)
    result = engine.evaluate("BTC/USDT:USDT", "LONG", now_ts=1)
    assert result["trade_allowed"] is False
    assert result["cooldown_remaining_seconds"] == 10_799


def test_future_signal_timestamp_fails_closed():
    engine = TradeCooldownEngine()
    engine.register_signal("ETH/USDT:USDT", "SHORT", now_ts=100)
    result = engine.evaluate("ETH/USDT:USDT", "SHORT", now_ts=90)
    assert result["trade_allowed"] is False
    assert result["reason"] == "Last signal timestamp is in the future"


def test_malformed_positions_do_not_crash_duplicate_guard():
    engine = TradeCooldownEngine()
    result = engine.evaluate(
        "BTC/USDT:USDT",
        "LONG",
        open_positions=[None, "bad", {"symbol": "BTC/USDT:USDT", "status": "OPEN"}],
        now_ts=0,
    )
    assert result["trade_allowed"] is False
    assert result["reason"] == "Open position already exists"


def test_non_directional_signals_are_not_registered():
    engine = TradeCooldownEngine()
    engine.register_signal("BTC/USDT:USDT", "WAIT", now_ts=0)
    assert engine.last_signals == {}
