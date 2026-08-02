import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from manual_trade_quality import ManualTradeQualityGate
from trade_journal import TradeJournal


def _base_payload(**overrides):
    payload = {
        "symbol": "BTC/USDT:USDT",
        "signal": {"signal": "LONG", "confidence": 92, "grade": "A+"},
        "entry": {"valid": True, "direction": "LONG", "entry": 100, "stop_loss": 99},
        "risk": {"selected_rr": 3.5, "risk": 1},
        "decision": {"action": "EXECUTE", "score": 88, "risk_valid": True, "mtf_valid": True},
        "confluence": {"score": 82},
        "market_phase": {"phase": "Expansion"},
        "trade_journal": None,
    }
    payload.update(overrides)
    return payload


def test_manual_quality_allows_strong_setup_without_history():
    result = ManualTradeQualityGate(Config).evaluate(**_base_payload())

    assert result["allowed"] is True
    assert result["score"] >= 75
    assert result["historical"]["warnings"]


def test_manual_quality_blocks_negative_historical_expectancy(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_HISTORICAL_MIN_TRADES", 3)
    journal = TradeJournal()
    for index, pnl_rr in enumerate([-1.0, -0.8, 0.5], start=1):
        trade = journal.register_trade(
            {"symbol": "BTC/USDT:USDT", "side": "LONG", "entry": 100, "stop_loss": 99, "rr": 3},
            symbol="BTC/USDT:USDT",
            timestamp=index,
        )
        trade["status"] = "CLOSED"
        trade["pnl_rr"] = pnl_rr
        trade["result"] = "WIN" if pnl_rr > 0 else "LOSS"
        trade["market_phase"] = "Expansion"

    result = ManualTradeQualityGate(Config).evaluate(**_base_payload(trade_journal=journal))

    assert result["allowed"] is False
    assert any("historical expectancy" in blocker for blocker in result["blockers"])
