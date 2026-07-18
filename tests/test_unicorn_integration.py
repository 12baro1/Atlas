import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confluence_engine import ConfluenceEngine
from signal_engine import SignalEngine
from telegram_engine import TelegramEngine


def _unicorn_payload(direction="BULLISH", confidence=84):
    return {
        "active": True,
        "confidence": confidence,
        "best": {
            "direction": direction,
            "timeframe": "15m",
            "entry": 101.5,
            "stop_loss": 100.8,
            "tp1": 102.5,
            "tp2": 103.2,
            "tp3": 104.4,
        },
    }


def test_confluence_scores_unicorn_bonus():
    confluence = ConfluenceEngine().evaluate(
        mtf={"valid": True},
        trend={"trend": "BULLISH"},
        entry={"direction": "LONG", "valid": True},
        confirmation={"confirmed": True},
        premium_discount={"valid": True},
        liquidity_sweep={"is_sweep": True, "strength_score": 82},
        ote={"valid": True},
        htf_orderblock={"valid": True},
        htf_fvg={"valid": True},
        killzone=True,
        session=True,
        breaker=[{"breaker": True}],
        smt={"active": True, "direction": "BULLISH", "confidence": 80},
        orderblocks=[{"type": "BULLISH"}],
        fvg=[{"type": "BULLISH"}],
        market_phase={"phase": "Expansion"},
        unicorn=_unicorn_payload(),
    )

    assert any("Unicorn" in item for item in confluence["checks"])
    assert confluence["score"] >= 110


def test_signal_includes_unicorn_fields():
    signal = SignalEngine().generate(
        {
            "entry": {"direction": "LONG"},
            "confluence": {"score": 90, "checks": ["ok"]},
            "market_phase": {"phase": "Expansion", "phase_score": 90, "phase_confidence": 80, "mtf_alignment": 100},
            "liquidity_sweep": {"is_sweep": True, "strength_score": 75, "post_structure": {"confirmed": True}},
            "smt": {"active": True, "confidence": 70},
            "unicorn": _unicorn_payload(),
        }
    )

    assert signal["unicorn_active"] is True
    assert signal["unicorn_confidence"] == 84


def test_telegram_formats_unicorn_section():
    message = TelegramEngine().format_signal(
        {
            "symbol": "BTC/USDT:USDT",
            "signal": {
                "signal": "LONG",
                "grade": "A+",
                "strength": "STRONG",
                "confidence": 92,
            },
            "entry": {
                "direction": "LONG",
                "valid": True,
                "entry": 101.5,
                "stop_loss": 100.8,
            },
            "risk": None,
            "rr": None,
            "confluence": {"checks": ["x"]},
            "market_phase": {"phase": "Expansion", "phase_confidence": 85, "mtf_alignment": 100},
            "unicorn": _unicorn_payload(),
        }
    )

    assert "UNICORN SETUP" in message
    assert "Direction : BULLISH" in message
    assert "TP3" in message
