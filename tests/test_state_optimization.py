"""StateEngine optimizasyon testleri: duplicate veri kaldırıldı, resume çalışıyor."""

import json

from core.candle import Candle
from state_engine import StateEngine


def _candle(time, price):
    return Candle(time=time, open=price, high=price + 1, low=price - 1, close=price, volume=100.0)


def _make_candles(n=30):
    return [_candle(1000 + i * 100, 10.0 + i) for i in range(n)]


def test_state_no_longer_stores_duplicate_lists(tmp_path):
    path = tmp_path / "state.json"
    engine = StateEngine(path=str(path))
    result = {
        "signal": {"signal": "WAIT"},
        "analysis": {
            "structure": [{"index": 1}],
            "fvg": [{"index": 2}],
            "liquidity": [{"index": 3}],
            "bos": [{"index": 4}],
            "choch": [{"index": 5}],
            "orderblocks": [{"index": 6}],
        },
    }
    engine.update_analysis_state("BTC/USDT:USDT", {"15m": [_candle(500, 10.0)]}, result)

    sym = engine.state["symbols"]["BTC/USDT:USDT"]
    # Üst seviye duplicate listeler artık yok
    assert "market_structure" not in sym
    assert "structure" not in sym
    # Ancak last_result hâlâ tam analizi taşıyor
    assert sym["last_result"]["analysis"]["structure"] == [{"index": 1}]
    assert sym["last_candle"] is not None


def test_save_then_reload_preserves_state(tmp_path):
    path = tmp_path / "state.json"
    engine = StateEngine(path=str(path))
    candles = [_candle(5000, 20.0)]
    engine.update_analysis_state("BTC/USDT:USDT", {"15m": candles}, {"signal": None})

    # Yeniden yükle
    engine2 = StateEngine(path=str(path))
    assert engine2.state["symbols"]["BTC/USDT:USDT"]["last_candle"]["time"] == 5000


def test_restore_cached_result_marks_cache_hit(tmp_path):
    path = tmp_path / "state.json"
    engine = StateEngine(path=str(path))
    candles = [_candle(7000, 30.0)]
    engine.update_analysis_state("BTC/USDT:USDT", {"15m": candles}, {"signal": "WAIT"})
    engine.state["symbols"]["BTC/USDT:USDT"]["last_result"] = {"signal": "WAIT"}

    restored = engine.restore_cached_result("BTC/USDT:USDT")
    assert restored is not None
    assert restored["incremental"]["cache_hit"] is True


def test_has_new_entry_candle_logic(tmp_path):
    engine = StateEngine(path=str(tmp_path / "s.json"))
    candles = [_candle(100, 1.0), _candle(200, 2.0)]
    assert engine.has_new_entry_candle("X", candles) is True  # hiç işlenmedi

    engine.state["symbols"]["X"] = {"last_candle": {"time": 200}}
    assert engine.has_new_entry_candle("X", candles) is False  # son mum aynı

    candles2 = [_candle(100, 1.0), _candle(300, 3.0)]
    assert engine.has_new_entry_candle("X", candles2) is True  # yeni mum


def test_rejects_save_no_leftover_tmp(tmp_path):
    path = tmp_path / "state.json"
    engine = StateEngine(path=str(path))
    engine.update_analysis_state("A", {"15m": [_candle(1, 1.0)]}, {"signal": None})
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_state_file_only_contains_one_result(tmp_path):
    path = tmp_path / "state.json"
    engine = StateEngine(path=str(path))
    engine.update_analysis_state(
        "BTC/USDT:USDT",
        {"15m": [_candle(9000, 5.0)]},
        {"signal": "SHORT", "analysis": {"structure": [{"i": 1}]}},
    )
    raw = json.loads(path.read_text())
    sym = raw["symbols"]["BTC/USDT:USDT"]
    # Yapı listesi sadece last_result içinde bir kez (üst seviyede değil)
    assert "structure" not in sym
    assert sym["last_result"]["analysis"]["structure"][0]["i"] == 1