import data_engine


def test_smt_universe_fetches_btc_eth_timeframes_once_and_reuses_cache(monkeypatch):
    data_engine.invalidate_all()
    calls = []

    def fake_fetch(symbol, timeframe, limit):
        calls.append((symbol, timeframe, limit))
        return [f"{symbol}:{timeframe}"]

    monkeypatch.setattr(data_engine, "_fetch", fake_fetch)
    first = data_engine.get_smt_universe()
    assert set(first) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert set(first["BTC/USDT:USDT"]) == {"15m", "1h", "4h", "1d"}
    assert len(calls) == 8

    second = data_engine.get_smt_universe()
    assert len(calls) == 8
    assert second["ETH/USDT:USDT"]["4h"] == first["ETH/USDT:USDT"]["4h"]


def test_failed_refresh_can_only_reuse_unexpired_benchmark(monkeypatch):
    monkeypatch.setattr(data_engine, "_smt_cache", {})
    now = [1000]
    monkeypatch.setattr(data_engine.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(data_engine, "fetch_candles", lambda *a, **kw: ["cached"])
    data_engine.get_smt_universe()

    def unavailable(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(data_engine, "fetch_candles", unavailable)
    now[0] += 46
    universe = data_engine.get_smt_universe(force_refresh=True)
    assert universe["BTC/USDT:USDT"]["15m"] == []
    assert universe["BTC/USDT:USDT"]["4h"] == ["cached"]
