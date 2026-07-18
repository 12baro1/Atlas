import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.candle import Candle
from engine import AtlasEngine
from telegram_engine import TelegramEngine


def _candle(index):
    return Candle(
        time=1_700_000_000_000 + (index * 60_000),
        open=100 + index,
        high=101 + index,
        low=99 + index,
        close=100.5 + index,
        volume=100.0,
    )


def test_telegram_message_hides_levels_when_entry_invalid():
    message = TelegramEngine().format_signal(
        {
            "symbol": "AGLD/USDT:USDT",
            "signal": {
                "signal": "SHORT",
                "grade": "S+",
                "strength": "ELITE",
                "confidence": 100,
            },
            "entry": {
                "direction": "SHORT",
                "valid": False,
                "entry": 0.17997,
                "stop_loss": 0.18231,
            },
            "risk": {
                "capital_at_risk": 10,
                "position_size": 6241.4514,
                "risk": 0.00234,
                "tp1": 0.17708,
                "tp2": 0.17646,
                "tp3": 0.17641,
                "rr": 1.52,
            },
            "rr": {"quality": "WEAK", "score": 45},
            "dynamic_tp": {"tp1": 0.17708, "tp2": 0.17646, "tp3": 0.17641},
            "confluence": {"checks": ["x"]},
            "market_phase": {"phase": "Expansion", "phase_confidence": 85, "mtf_alignment": 100},
            "decision": {"action": "SHORT", "reason": "x"},
        }
    )

    assert "Entry levels : withheld (invalid entry)" in message
    assert "Capital At Risk" not in message
    assert "TP1 :" not in message


def test_notify_if_elite_skips_invalid_entry_before_sending(monkeypatch):
    engine = AtlasEngine()

    called = {"count": 0}

    class _DummyBot:
        def send(self, _message):
            called["count"] += 1
            return True

    class _DummyEngine:
        def format_signal(self, _result):
            return "dummy"

    import telegram_engine as telegram_module
    monkeypatch.setattr(telegram_module, "TelegramBot", lambda: _DummyBot())

    engine.telegram = _DummyEngine()

    sent = engine._notify_if_elite(
        data={"symbol": "AGLD/USDT:USDT"},
        signal={"signal": "SHORT", "confidence": 95, "grade": "A+", "strength": "STRONG"},
        entry={"direction": "SHORT", "valid": False, "entry": 1.0, "stop_loss": 1.1},
        risk={"entry": 1.0, "stop_loss": 1.1, "risk": 0.1, "rr": 1.5},
        rr={"quality": "WEAK", "score": 45},
        dynamic_tp={"tp1": 0.9, "tp2": 0.8, "tp3": 0.7},
        confluence={"checks": []},
        market_phase={"phase": "Expansion"},
        unicorn={"active": False},
        cisd={"active": False},
        institutional={"active": False},
        decision={"action": "SHORT"},
    )

    assert sent is False
    assert called["count"] == 0


def test_telegram_message_compact_mode_reduces_clutter():
    checks = [
        "✔ Multi Timeframe",
        "✔ Trend",
        "✔ Entry",
        "◐ Liquidity Breakout",
        "✘ OTE",
        "✘ SMT",
        "✘ Unicorn",
        "✘ Stack Confluence",
    ]

    message = TelegramEngine().format_signal(
        {
            "symbol": "MARA/USDT:USDT",
            "signal": {
                "signal": "SHORT",
                "grade": "S+",
                "strength": "ELITE",
                "confidence": 100,
            },
            "entry": {
                "direction": "SHORT",
                "valid": True,
                "entry": 11.18,
                "stop_loss": 11.2,
            },
            "risk": {
                "capital_at_risk": 10,
                "capital_at_risk_target": 10,
                "risk_percent": 1,
                "position_size": 500,
                "risk": 0.02,
                "tp1": 11.15,
                "tp2": 11.13,
                "tp3": 11.10,
                "rr": 4,
                "net_rr": 3.7,
            },
            "rr": {"quality": "VERY GOOD", "score": 90},
            "dynamic_tp": {"tp1": 11.15, "tp2": 11.13, "tp3": 11.10},
            "confluence": {"checks": checks},
            "market_phase": {"phase": "Expansion", "phase_confidence": 85, "mtf_alignment": 100},
            "decision": {"action": "SHORT", "reason": "A" * 250},
        }
    )

    assert "Passed: 3 | Partial: 1 | Failed: 4" in message
    assert "Target Risk Capital" not in message
    assert "Risk %" not in message
    assert "Net RR (Cost Adj.)" not in message
    assert "Reason : " in message
    assert ("A" * 170) not in message
