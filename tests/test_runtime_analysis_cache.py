import threading

from atlas_runtime import AtlasRuntime


def _runtime_with_cache(entries):
    runtime = AtlasRuntime.__new__(AtlasRuntime)
    runtime._lock = threading.Lock()
    runtime._latest_analysis_by_symbol = {}
    runtime._latest_analysis_at = {}
    for symbol, analyzed_at in entries.items():
        runtime._latest_analysis_by_symbol[symbol] = {"symbol": symbol}
        runtime._latest_analysis_at[symbol] = analyzed_at
    return runtime


def test_analysis_cache_prunes_entries_older_than_configured_age(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "ANALYSIS_CACHE_MAX_AGE_SECONDS", 60)
    monkeypatch.setattr(Config, "ANALYSIS_CACHE_MAX_SYMBOLS", 10)
    runtime = _runtime_with_cache({"OLD/USDT": 1_000, "FRESH/USDT": 95_000})

    runtime._prune_latest_analyses(now_ms=100_000)

    assert list(runtime._latest_analysis_by_symbol) == ["FRESH/USDT"]
    assert list(runtime._latest_analysis_at) == ["FRESH/USDT"]


def test_analysis_cache_keeps_newest_symbols_when_cap_is_exceeded(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "ANALYSIS_CACHE_MAX_AGE_SECONDS", 86_400)
    monkeypatch.setattr(Config, "ANALYSIS_CACHE_MAX_SYMBOLS", 2)
    runtime = _runtime_with_cache({
        "BTC/USDT": 1_000,
        "ETH/USDT": 2_000,
        "SOL/USDT": 3_000,
    })

    runtime._prune_latest_analyses(now_ms=4_000)

    assert set(runtime._latest_analysis_by_symbol) == {"ETH/USDT", "SOL/USDT"}
    assert set(runtime._latest_analysis_at) == {"ETH/USDT", "SOL/USDT"}


def test_latest_analyses_also_prunes_expired_entries(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "ANALYSIS_CACHE_MAX_AGE_SECONDS", 60)
    monkeypatch.setattr(Config, "ANALYSIS_CACHE_MAX_SYMBOLS", 10)
    runtime = _runtime_with_cache({"STALE/USDT": 1_000, "FRESH/USDT": 95_000})

    results = runtime.latest_analyses(max_age_seconds=120)

    assert [item["symbol"] for item in results] == ["FRESH/USDT"]
    assert set(runtime._latest_analysis_by_symbol) == {"FRESH/USDT"}
