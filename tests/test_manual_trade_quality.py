import os
import sys
import math

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


def test_manual_quality_does_not_use_other_symbols_history(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_HISTORICAL_MIN_TRADES", 1)
    journal = TradeJournal()
    trade = journal.register_trade(
        {"symbol": "ETH/USDT:USDT", "side": "LONG", "entry": 100, "stop_loss": 99, "rr": 3},
        symbol="ETH/USDT:USDT",
        timestamp=1,
    )
    trade["status"] = "CLOSED"
    trade["pnl_rr"] = 5.0
    trade["result"] = "WIN"
    trade["market_phase"] = "Expansion"

    result = ManualTradeQualityGate(Config).evaluate(**_base_payload(trade_journal=journal))

    assert result["historical"]["sample_size"] == 0
    assert result["historical"]["scope"] == "no_matching_symbol_history"
    assert any("no closed trades for symbol BTC/USDT:USDT" in warning for warning in result["warnings"])
    assert result["historical"]["score"] == 5


def test_manual_quality_prefers_matching_symbol_and_direction(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_HISTORICAL_MIN_TRADES", 2)
    journal = TradeJournal()
    for index, (symbol, side, pnl_rr) in enumerate(
        [
            ("BTC/USDT:USDT", "LONG", 1.0),
            ("BTC/USDT:USDT", "LONG", 1.0),
            ("BTC/USDT:USDT", "SHORT", -1.0),
            ("ETH/USDT:USDT", "LONG", -2.0),
        ],
        start=1,
    ):
        trade = journal.register_trade(
            {"symbol": symbol, "side": side, "entry": 100, "stop_loss": 99, "rr": 3},
            symbol=symbol,
            timestamp=index,
        )
        trade["status"] = "CLOSED"
        trade["pnl_rr"] = pnl_rr
        trade["result"] = "WIN" if pnl_rr > 0 else "LOSS"
        trade["market_phase"] = "Expansion"

    result = ManualTradeQualityGate(Config).evaluate(**_base_payload(trade_journal=journal))

    assert result["historical"]["sample_size"] == 2
    assert result["historical"]["scope"] == "symbol_and_direction"
    assert result["historical"]["expectancy"] == 1.0
    assert result["historical"]["score"] == 15


def test_manual_quality_sanitizes_nan_and_infinite_inputs():
    gate = ManualTradeQualityGate(Config)
    result = gate.evaluate(
        **_base_payload(
            signal={"signal": "LONG", "confidence": float("nan"), "learning": {"matched": False}},
            confluence={"score": float("inf")},
            risk={"selected_rr": float("nan")},
        )
    )

    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert all(math.isfinite(value) for value in result["components"].values())
    assert gate._num(float("nan"), 7) == 7
    assert gate._num(float("inf"), 9) == 9
