import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.candle import Candle
from state_engine import StateEngine
from economic_news_engine import EconomicNewsFilter
from trade_cooldown_engine import TradeCooldownEngine
from position_manager import PositionManager
from learning_engine import LearningEngine


def test_state_engine_persists_analysis_and_incremental_cache(tmp_path):
    path = tmp_path / "state.json"
    engine = StateEngine(path)
    candles = [Candle(1, 1, 2, 0.5, 1.5, 10)]
    result = {
        "analysis": {"structure": [{"label": "HH"}], "bos": [], "choch": [], "fvg": [], "orderblocks": [], "liquidity": []},
        "signal": {"signal": "LONG"},
        "risk": {"rr": 3},
        "decision": {"action": "EXECUTE"},
    }
    engine.update_analysis_state("BTC/USDT:USDT", {"15m": candles}, result)

    restored = StateEngine(path)
    assert not restored.has_new_entry_candle("BTC/USDT:USDT", candles)
    assert restored.restore_cached_result("BTC/USDT:USDT")["incremental"]["cache_hit"] is True


def test_news_filter_blocks_high_impact_window():
    event_time = 1_700_000_000_000
    news = EconomicNewsFilter()
    state = news.evaluate(timestamp_ms=event_time, events=[{"title": "US CPI", "impact": "HIGH", "time": event_time}])
    assert state["trade_allowed"] is False
    assert state["active"] is True


def test_position_manager_moves_sl_to_entry_and_scales_out():
    manager = PositionManager()
    manager.open("BTC", {"side": "LONG", "entry": 100, "stop_loss": 95, "tp1": 105, "tp2": 110, "tp3": 120})
    manager.update("BTC", 106)
    pos = manager.open_positions()[0]
    assert pos["stop_loss"] == 100
    assert pos["remaining_percent"] == 70
    assert pos["hit_tp1"] is True


def test_cooldown_blocks_duplicate_symbol_direction():
    cooldown = TradeCooldownEngine()
    cooldown.register_signal("ETH", "LONG", now_ts=100)
    state = cooldown.evaluate("ETH", "LONG", now_ts=110)
    assert state["trade_allowed"] is False


def test_learning_engine_adjusts_successful_setup_weight(tmp_path):
    learning = LearningEngine(tmp_path / "learning.json")
    for _ in range(5):
        learning.record_closed_trade({"side": "LONG", "result": "WIN", "metadata": {"setup_type": "market_structure"}})
    rates = learning.setup_success_rates()
    assert rates["market_structure"]["weight"] > 1
